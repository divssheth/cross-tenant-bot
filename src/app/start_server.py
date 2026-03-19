"""
Server module for the Cross-Tenant Teams Bot.
Handles HTTP request routing and agent process initialization.
"""
import os
import uuid
import logging
import jwt as pyjwt
from os import environ
from microsoft_agents.hosting.core import AgentApplication, AgentAuthConfiguration
from microsoft_agents.hosting.core.authorization import JwtTokenValidator
from microsoft_agents.hosting.aiohttp import (
    start_agent_process,
    CloudAdapter,
)
from aiohttp.web import Request, Response, Application, run_app, json_response, middleware
from typing import Optional, Callable, Awaitable

from app.trace_config import trace_id, traceparent

logger = logging.getLogger("cross-tenant-bot.server")


# Health check endpoints that should bypass JWT authentication
HEALTH_CHECK_PATHS = {'/startup', '/ready', '/live'}


@middleware
async def conditional_jwt_middleware(request: Request, handler: Callable[[Request], Awaitable[Response]]):
    """
    Custom middleware that conditionally applies JWT authentication.
    Skips JWT validation for health check endpoints while requiring it for API endpoints.
    """
    # Skip JWT validation for health check endpoints
    if request.path in HEALTH_CHECK_PATHS:
        logger.debug(f"Bypassing JWT auth for health check endpoint: {request.path}")
        return await handler(request)
    
    # Apply JWT validation for all other endpoints
    auth_config: AgentAuthConfiguration = request.app["agent_configuration"]
    token_validator = JwtTokenValidator(auth_config)
    auth_header = request.headers.get("Authorization")
    
    if auth_header:
        # Extract the token from the Authorization header
        token = auth_header.split(" ")[1]
        
        # Debug: Decode token without verification to see its contents
        try:
            unverified_payload = pyjwt.decode(token, options={"verify_signature": False})
            logger.info(f"🔍 JWT Token Debug Info:")
            logger.info(f"  Token audience (aud): {unverified_payload.get('aud', 'NOT FOUND')}")
            logger.info(f"  Expected CLIENT_ID: {auth_config.CLIENT_ID}")
            logger.info(f"  Token issuer (iss): {unverified_payload.get('iss', 'NOT FOUND')}")
            logger.info(f"  Token appid: {unverified_payload.get('appid', 'NOT FOUND')}")
        except Exception as debug_e:
            logger.warning(f"Could not decode token for debugging: {debug_e}")
        
        try:
            claims = await token_validator.validate_token(token)
            request["claims_identity"] = claims
        except ValueError as e:
            logger.error(f"JWT validation error: {e}")
            return json_response({"error": str(e)}, status=401)
    else:
        if not auth_config or not auth_config.CLIENT_ID:
            # Allow anonymous if no auth config
            request["claims_identity"] = token_validator.get_anonymous_claims()
        else:
            return json_response(
                {"error": "Authorization header not found"}, status=401
            )
    
    return await handler(request)


class ApiMessagesOnlyLogFilter(logging.Filter):
    """Only allow access logs for /api/messages endpoints."""
    
    ALLOWED_PATH = "/api/messages"
    
    def filter(self, record: logging.LogRecord) -> bool:
        """Return True only for /api/messages endpoint logs."""
        # Check if the log message contains the allowed path
        message = record.getMessage()
        return self.ALLOWED_PATH in message


def start_server(
        agent_application: AgentApplication, auth_configuration: Optional[AgentAuthConfiguration]
):
    """
    Start the web server to handle incoming bot messages.

    Args:
        agent_application: The configured AgentApplication instance
        auth_configuration: Authentication configuration (can be None for anonymous mode)
    """

    async def entry_point(req: Request) -> Response:
        trace_id.set(uuid.uuid4().hex)
        traceparent.set(f"00-{trace_id.get()}-{os.urandom(8).hex()}-00")

        agent: AgentApplication = req.app["agent_app"]
        adapter: CloudAdapter = req.app["adapter"]
        result = await start_agent_process(
            req,
            agent,
            adapter
        )
        return result if result is not None else Response(status=200)

    async def health_check(_: Request) -> Response:
        return Response(status=200)

    APP = Application(middlewares=[conditional_jwt_middleware])
    APP.router.add_post("/api/messages", entry_point)
    APP.router.add_get("/api/messages", health_check)

    APP.router.add_get("/startup", health_check)
    APP.router.add_get("/ready", health_check)
    APP.router.add_get("/live", health_check)

    APP["agent_configuration"] = auth_configuration
    APP["agent_app"] = agent_application
    APP["adapter"] = agent_application.adapter

    async def _on_cleanup(app: Application):
        """Clean up agent resources on server shutdown."""
        try:
            from app.agents.foundry_agent_client import get_agent_client
            client = get_agent_client()
            if client:
                await client.cleanup()
        except Exception as e:
            logger.warning("Error during agent cleanup: %s", e)

    APP.on_cleanup.append(_on_cleanup)

    # Configure access logger to only allow /api/messages logs
    access_logger = logging.getLogger("aiohttp.access")
    access_logger.addFilter(ApiMessagesOnlyLogFilter())

    try:
        port = int(environ.get("PORT", 3978))
        run_app(APP, host="0.0.0.0", port=port, access_log=access_logger)
    except Exception as error:
        raise error
