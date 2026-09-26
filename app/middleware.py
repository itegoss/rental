import logging
from django.shortcuts import redirect
from django.contrib import messages
from social_django.middleware import SocialAuthExceptionMiddleware
from social_core.exceptions import AuthCanceled, AuthFailed, AuthTokenError, SocialAuthBaseException

logger = logging.getLogger(__name__)


class CustomSocialAuthExceptionMiddleware(SocialAuthExceptionMiddleware):
    """
    Safely captures all Social Auth exceptions (like AuthCanceled when a user cancels
    Google login or when an OAuth token exchange fails/times out) and gracefully redirects
    to signin with a friendly message instead of showing a 500 / debug crash page.
    """

    def process_exception(self, request, exception):
        if isinstance(exception, SocialAuthBaseException):
            message = self.get_message(request, exception)
            url = self.get_redirect_uri(request, exception)
            try:
                messages.error(request, message)
            except Exception:
                pass
            return redirect(url or "/signin/")
        return None

    def get_message(self, request, exception):
        if isinstance(exception, AuthCanceled):
            return "Google sign-in was canceled. Please try again or use your mobile number."
        logger.warning(f"[SocialAuth Error] {type(exception).__name__}: {exception}")
        return "Unable to sign in with Google at this moment. Please try again or sign in using your mobile number."

    def get_redirect_uri(self, request, exception):
        return "/signin/"
