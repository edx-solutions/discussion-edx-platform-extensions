"""
Unit tests for compute_social_engagement_score command
"""
from mock import patch

from django.conf import settings
from django.core.management import call_command

from xmodule.modulestore.tests.django_utils import SharedModuleStoreTestCase
from xmodule.modulestore.tests.factories import CourseFactory
from student.tests.factories import UserFactory, CourseEnrollmentFactory
from social_engagement.models import StudentSocialEngagementScore


@patch.dict(settings.FEATURES, {'ENABLE_SOCIAL_ENGAGEMENT': True})
class TestComputeSocialScoreCommand(SharedModuleStoreTestCase):
    """
    Tests the `compute_social_engagement_score` command.
    """
    @classmethod
    def setUpClass(cls):
        super(TestComputeSocialScoreCommand, cls).setUpClass()

        cls.course = CourseFactory.create()
        cls.users = []
        for __ in range(1, 5):
            user = UserFactory.create()
            cls.users.append(user)
            CourseEnrollmentFactory(user=user, course_id=cls.course.id)

    def test_compute_social_engagement_score(self):
        """
        Test to ensure all users enrolled in course have their social scores computed
        """
        with patch('social_engagement.engagement._get_user_social_stats') as mock_func:
            mock_func.return_value = {
                'num_threads': 1,
                'num_comments': 1,
                'num_replies': 1,
                'num_upvotes': 1,
                'num_thread_followers': 1,
                'num_comments_generated': 1,
            }
            call_command('compute_social_engagement_score', course_id=unicode(self.course.id))
        users_count = StudentSocialEngagementScore.objects.filter(course_id=self.course.id).count()
        self.assertEqual(users_count, len(self.users))
