"""Discord publishing adapter using discord.py.

Lifecycle strategy: for an occasional publishing task (a few messages a day) it
is not worth keeping a bot permanently connected. Each publication opens a
client session, waits for `on_ready`, sends the message, and closes. Sending is
wrapped in retries with exponential backoff.
"""

from __future__ import annotations

import asyncio

import discord
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.logging import get_logger
from app.domain.entities import PublishableJobOffer
from app.infrastructure.discord.embed_builder import build_job_embed, build_summary_embed
from app.interfaces.publisher import Publisher, PublisherError

logger = get_logger(__name__)

# Hard ceiling for the whole login + send cycle. If the gateway is unreachable
# (no outbound WebSocket, blocked network) we fail fast with a clear message
# instead of hanging on discord.py's internal reconnection loop.
_CONNECT_TIMEOUT_SECONDS = 30.0
# Extra budget per offer for the batch cycle, on top of the connect ceiling, so
# creating a thread + sending its message per offer (possibly rate-limited) does
# not trip the timeout.
_PER_OFFER_TIMEOUT_SECONDS = 15.0
# Discord thread auto-archive after inactivity (minutes); 1440 = 24h.
_THREAD_AUTO_ARCHIVE_MINUTES = 1440
# Discord caps thread names at 100 characters.
_MAX_THREAD_NAME = 100


def _thread_name(post: PublishableJobOffer) -> str:
    """Thread title for an offer: its edited headline, trimmed to Discord's cap."""
    title = post.edited.title.strip() or "Oferta de empleo"
    return title[: _MAX_THREAD_NAME - 1] + "…" if len(title) > _MAX_THREAD_NAME else title


class DiscordPublisher(Publisher):
    """Publishes job offers as embeds in a Discord channel."""

    def __init__(self, token: str, channel_id: int) -> None:
        if not token or not channel_id:
            raise ValueError("DISCORD_TOKEN y DISCORD_CHANNEL_ID son obligatorios")
        self._token = token
        self._channel_id = channel_id

    async def _send(
        self,
        *,
        content: str | None = None,
        embed: discord.Embed | None = None,
    ) -> int:
        """Open an ephemeral client session and send a message to the channel."""
        target_channel = self._channel_id
        intents = discord.Intents.none()
        client = discord.Client(intents=intents)
        result: dict[str, int | Exception] = {}

        @client.event
        async def on_ready() -> None:
            try:
                channel = client.get_channel(target_channel) or await client.fetch_channel(
                    target_channel
                )
                if not isinstance(channel, discord.abc.Messageable):
                    raise PublisherError(f"El canal {target_channel} no admite mensajes")
                message = await channel.send(content=content, embed=embed)
                result["message_id"] = message.id
            except discord.Forbidden as exc:
                result["error"] = PublisherError(
                    f"El bot no tiene permisos en el canal {target_channel} "
                    f"(necesita Ver canal + Enviar mensajes + Insertar enlaces): {exc}"
                )
            except discord.NotFound as exc:
                result["error"] = PublisherError(
                    f"Canal {target_channel} no encontrado; revisa la configuración "
                    f"y que el bot esté en ese servidor: {exc}"
                )
            except Exception as exc:
                result["error"] = exc
            finally:
                await client.close()

        try:
            async with asyncio.timeout(_CONNECT_TIMEOUT_SECONDS):
                await client.start(self._token)
        except discord.LoginFailure as exc:
            raise PublisherError(
                f"Token de Discord inválido (revisa DISCORD_TOKEN): {exc}"
            ) from exc
        except TimeoutError as exc:
            await client.close()
            raise PublisherError(
                "Timeout conectando al gateway de Discord; revisa la conectividad "
                "de red saliente (wss://gateway.discord.gg) desde el contenedor"
            ) from exc
        except (discord.HTTPException, OSError) as exc:
            raise PublisherError(f"No se pudo conectar con Discord: {exc}") from exc

        if "error" in result:
            raise PublisherError(str(result["error"]))
        if "message_id" not in result:
            raise PublisherError("Discord cerró la sesión sin confirmar el envío")
        return int(result["message_id"])

    @retry(
        retry=retry_if_exception_type((discord.HTTPException, ConnectionError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=20),
        reraise=True,
    )
    async def publish(self, post: PublishableJobOffer) -> int:
        embed = build_job_embed(post)
        message_id = await self._send(embed=embed)
        logger.info("discord.published", message_id=message_id, title=post.edited.title)
        return message_id

    async def _send_batch(
        self,
        posts: list[PublishableJobOffer],
        summary_embed: discord.Embed,
    ) -> list[int | None]:
        """Open one session: post the summary, then one thread per offer.

        Posts the daily header in the channel and, for each offer, opens its own
        public thread (named after the offer) and sends the offer embed inside.
        Per-offer failures are swallowed (recorded as ``None``) so a single bad
        offer does not abort the rest of the batch. Only a failure to connect or
        to post the summary aborts the whole publication.
        """
        target_channel = self._channel_id
        intents = discord.Intents.none()
        client = discord.Client(intents=intents)
        result: dict[str, object] = {}

        @client.event
        async def on_ready() -> None:
            try:
                channel = client.get_channel(target_channel) or await client.fetch_channel(
                    target_channel
                )
                if not isinstance(channel, discord.abc.Messageable):
                    raise PublisherError(f"El canal {target_channel} no admite mensajes")
                if not hasattr(channel, "create_thread"):
                    raise PublisherError(
                        f"El canal {target_channel} no admite hilos; usa un canal de "
                        "texto del servidor para publicar cada oferta en su hilo"
                    )
                summary = await channel.send(embed=summary_embed)
                message_ids: list[int | None] = []
                for post in posts:
                    try:
                        thread = await channel.create_thread(
                            name=_thread_name(post),
                            type=discord.ChannelType.public_thread,
                            auto_archive_duration=_THREAD_AUTO_ARCHIVE_MINUTES,
                        )
                        message = await thread.send(embed=build_job_embed(post))
                        message_ids.append(message.id)
                    except discord.HTTPException as exc:
                        logger.warning(
                            "discord.thread_create_failed",
                            title=post.edited.title,
                            error=str(exc),
                        )
                        message_ids.append(None)
                result["summary_id"] = summary.id
                result["message_ids"] = message_ids
            except discord.Forbidden as exc:
                result["error"] = PublisherError(
                    f"El bot no tiene permisos suficientes en el canal {target_channel} "
                    f"(necesita Ver canal + Enviar mensajes + Insertar enlaces + "
                    f"Crear hilos públicos + Enviar mensajes en hilos): {exc}"
                )
            except discord.NotFound as exc:
                result["error"] = PublisherError(
                    f"Canal {target_channel} no encontrado; revisa la configuración "
                    f"y que el bot esté en ese servidor: {exc}"
                )
            except PublisherError as exc:
                result["error"] = exc
            except Exception as exc:
                result["error"] = exc
            finally:
                await client.close()

        timeout = _CONNECT_TIMEOUT_SECONDS + _PER_OFFER_TIMEOUT_SECONDS * len(posts)
        try:
            async with asyncio.timeout(timeout):
                await client.start(self._token)
        except discord.LoginFailure as exc:
            raise PublisherError(
                f"Token de Discord inválido (revisa DISCORD_TOKEN): {exc}"
            ) from exc
        except TimeoutError as exc:
            await client.close()
            raise PublisherError(
                "Timeout conectando al gateway de Discord; revisa la conectividad "
                "de red saliente (wss://gateway.discord.gg) desde el contenedor"
            ) from exc
        except (discord.HTTPException, OSError) as exc:
            raise PublisherError(f"No se pudo conectar con Discord: {exc}") from exc

        if "error" in result:
            raise PublisherError(str(result["error"]))
        if "message_ids" not in result:
            raise PublisherError("Discord cerró la sesión sin confirmar el envío")
        return result["message_ids"]  # type: ignore[return-value]

    @retry(
        retry=retry_if_exception_type((discord.HTTPException, ConnectionError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=20),
        reraise=True,
    )
    async def publish_batch(
        self, posts: list[PublishableJobOffer], *, summary_date: str
    ) -> list[int | None]:
        if not posts:
            return []
        summary_embed = build_summary_embed(posts, date_label=summary_date)
        message_ids = await self._send_batch(posts, summary_embed)
        logger.info(
            "discord.batch_published",
            published=sum(1 for mid in message_ids if mid is not None),
            total=len(posts),
        )
        return message_ids

    async def publish_test_message(self, text: str) -> int:
        message_id = await self._send(content=f"✅ Anfaia Jobs AI · test\n{text}")
        logger.info("discord.test_published", message_id=message_id)
        return message_id
