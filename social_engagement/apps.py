"""
app configuration
"""
from django.apps import AppConfig


class SolutionsAppSocialEngagementConfig(AppConfig):

    name = 'social_engagement'
    verbose_name = 'social_engagement app'

    def ready(self):

        # import signal handlers
        import social_engagement.handlers  # pylint: disable=unused-import
