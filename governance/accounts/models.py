import datetime as dt
import hashlib
import secrets

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **kwargs):
        user = self.model(email=self.normalize_email(email), **kwargs)
        user.set_password(password)
        user.save()
        return user

    def create_superuser(self, email, password=None, **kwargs):
        return self.create_user(email, password, is_admin=True, **kwargs)

    def active(self):
        return self.filter(is_active=True)


class User(AbstractBaseUser):
    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"

    email = models.EmailField(_("email"), max_length=254, unique=True)
    full_name = models.CharField(_("full name"), max_length=200, blank=True)
    short_name = models.CharField(_("short name"), max_length=30, blank=True)
    language = models.CharField(
        _("language"), max_length=10, choices=settings.LANGUAGES, blank=True
    )
    is_active = models.BooleanField(_("is active"), default=True)
    is_admin = models.BooleanField(_("is admin"), default=False)
    notify_all = models.BooleanField(
        _("inform me about everything in all circles"),
        default=False,
        help_text=_("By default mails are about the circles one is a member of."),
    )
    glassfrog_id = models.BigIntegerField(
        _("GlassFrog ID"), null=True, blank=True, unique=True
    )

    objects = UserManager()

    class Meta:
        ordering = [Lower("full_name"), "email"]
        verbose_name = _("user")
        verbose_name_plural = _("users")

    def __str__(self):
        return self.full_name or self.email

    def get_absolute_url(self):
        from django.urls import reverse

        return reverse("person", kwargs={"pk": self.pk})

    def get_full_name(self):
        return str(self)

    def get_short_name(self):
        return self.short_name or self.email.split("@")[0]

    @property
    def is_staff(self):
        return self.is_admin

    def has_perm(self, perm, obj=None):
        return self.is_active and self.is_admin

    def has_module_perms(self, app_label):
        return self.is_active and self.is_admin


# Created on the API tokens page or by `gov login` (/cli-login/), which asks
# for a new one through the browser when the old one expired. Each use
# extends it: a token in use (e.g. of the daily backup) stays valid, one
# nobody uses expires.
API_TOKEN_LIFETIME = dt.timedelta(days=30)


def _api_token_expiry():
    return timezone.now() + API_TOKEN_LIFETIME


def _hash_api_token(secret):
    return hashlib.sha256(secret.encode()).hexdigest()


class APITokenQuerySet(models.QuerySet):
    def for_secret(self, secret):
        """The valid token of an active user, or None"""
        token = (
            self
            .filter(
                key_hash=_hash_api_token(secret),
                expires_at__gt=timezone.now(),
                user__is_active=True,
            )
            .select_related("user")
            .first()
        )
        if not token:
            return None
        now = timezone.now()
        self.filter(pk=token.pk).update(
            last_used_at=now, expires_at=now + API_TOKEN_LIFETIME
        )
        return token


class APIToken(models.Model):
    """Personal API tokens like in Workbench, only their hash is stored"""

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="api_tokens",
        verbose_name=_("user"),
    )

    class Access(models.TextChoices):
        READ = "read", _("read only")
        WRITE = "write", _("read and write")

    title = models.CharField(_("title"), max_length=100)
    # No default: People decide which access their tools get
    access = models.CharField(_("access"), max_length=10, choices=Access.choices)
    key_hash = models.CharField(
        _("key hash"), max_length=64, unique=True, editable=False
    )
    created_at = models.DateTimeField(_("created at"), default=timezone.now)
    last_used_at = models.DateTimeField(_("last used at"), blank=True, null=True)
    expires_at = models.DateTimeField(_("expires at"), default=_api_token_expiry)

    objects = APITokenQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("API token")
        verbose_name_plural = _("API tokens")

    def __str__(self):
        return self.title

    @classmethod
    def create_for(cls, *, user, title, access):
        """Creates a token and returns it with its secret, which can't be
        shown again. Expired tokens of the user are removed."""
        cls.objects.filter(user=user, expires_at__lte=timezone.now()).delete()
        secret = f"gov_{secrets.token_urlsafe(32)}"
        token = cls.objects.create(
            user=user,
            title=title,
            access=cls.Access(access),
            key_hash=_hash_api_token(secret),
        )
        return token, secret


def prune_api_tokens():
    """Expired tokens go after another lifetime (fairy tasks)"""
    return APIToken.objects.filter(
        expires_at__lte=timezone.now() - API_TOKEN_LIFETIME
    ).delete()
