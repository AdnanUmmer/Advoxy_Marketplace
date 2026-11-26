from django.contrib.staticfiles.apps import StaticFilesConfig


class AdvoxyStaticFilesConfig(StaticFilesConfig):
    """collectstatic skips static/src/ (Tailwind sources; only the built static/css/app.css ships)."""

    ignore_patterns = [*StaticFilesConfig.ignore_patterns, "src"]
