"""
Unit tests for compute_social_engagement_score command
"""
from mock import patch
from datetime import datetime

from django.conf import settings
from django.core.management import call_command

from openedx.core.djangoapps.content.course_overviews.models import CourseOverview
from xmodule.modulestore.tests.django_utils import SharedModuleStoreTestCase
from xmodule.modulestore.tests.factories import CourseFactory
from student.models import CourseEnrollment
from student.tests.factories import UserFactory, CourseEnrollmentFactory
from social_engagement.models import StudentSocialEngagementScore


@patch.dict(settings.FEATURES, {'ENABLE_SOCIAL_ENGAGEMENT': True})
class TestComputeSocialScoreCommand(SharedModuleStoreTestCase):
    """
    Tests the `compute_social_engagement_score` command.
    """
    DEFAULT_STATS = {
        'num_threads': 1,
        'num_comments': 1,
        'num_replies': 1,
        'num_upvotes': 1,
        'num_thread_followers': 1,
        'num_comments_generated': 1,
    }

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
        user_ids = [user.id for user in self.users]
        with patch('social_engagement.engagement._get_course_social_stats') as mock_func:
            mock_func.return_value = ((user_id, self.DEFAULT_STATS) for user_id in user_ids)
            call_command('compute_social_engagement_score', course_id=unicode(self.course.id))
        users_count = StudentSocialEngagementScore.objects.filter(course_id=self.course.id).count()
        self.assertEqual(users_count, len(self.users))

    def test_compute_social_engagement_score_for_all_courses(self):
        """
        Test to ensure all users enrolled in all open courses have their social scores computed
        """
        course_open = CourseFactory.create()
        course_closed = CourseFactory.create(
            start=datetime(2014, 4, 16, 14, 30),
            end=datetime(2014, 6, 16, 14, 30),
        )
        # Load CourseOverview to cache course metadata
        __ = CourseOverview.get_from_id(course_open.id)
        __ = CourseOverview.get_from_id(course_closed.id)
        __ = CourseOverview.get_from_id(self.course.id)

        user_ids = [user.id for user in self.users]

        for idx in range(1, 10):
            user = UserFactory.create()
            CourseEnrollmentFactory(
                user=user,
                course_id=course_open.id if idx % 2 == 0 else course_closed.id
            )
            if idx % 2 == 0:
                user_ids.append(user.id)

        with patch(
            'social_engagement.management.commands.compute_social_engagement_score.query_yes_no'
        ) as patched_yes_no:
            patched_yes_no.return_value = True

            course1_users = CourseEnrollment.objects.num_enrolled_in(course_open.id)
            course2_users = CourseEnrollment.objects.num_enrolled_in(self.course.id)

            with patch('social_engagement.engagement._get_course_social_stats') as mock_func:
                mock_func.return_value = ((user_id, self.DEFAULT_STATS) for user_id in user_ids)
                call_command('compute_social_engagement_score', compute_for_all_open_courses=True)
        users_count = StudentSocialEngagementScore.objects.all().count()
        open_course_users_count = course1_users + course2_users
        self.assertEqual(users_count, open_course_users_count)
