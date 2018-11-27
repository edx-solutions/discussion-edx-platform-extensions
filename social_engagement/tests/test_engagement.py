"""
Tests for the social_engagment subsystem

paver test_system -s lms --test_id=lms/djangoapps/social_engagements/tests/test_engagement.py
"""

from django.conf import settings
from django.db import IntegrityError

from mock import patch
from datetime import datetime, timedelta
import pytz
import ddt

from student.tests.factories import UserFactory
from student.models import CourseEnrollment
from xmodule.modulestore.tests.factories import CourseFactory

from social_engagement.models import StudentSocialEngagementScore, StudentSocialEngagementScoreHistory

from social_engagement.engagement import update_course_engagement, _detail_results_factory, \
    _get_details_for_deletion

from edx_notifications.startup import initialize as initialize_notifications
from edx_notifications.lib.consumer import get_notifications_count_for_user
from xmodule.modulestore import ModuleStoreEnum
from xmodule.modulestore.tests.django_utils import (
    ModuleStoreTestCase,
    TEST_DATA_SPLIT_MODULESTORE
)


@patch.dict(settings.FEATURES, {'ENABLE_NOTIFICATIONS': True})
@patch.dict(settings.FEATURES, {'ENABLE_SOCIAL_ENGAGEMENT': True})
@ddt.ddt
class StudentEngagementTests(ModuleStoreTestCase):
    """ Test suite for CourseModuleCompletion """

    MODULESTORE = TEST_DATA_SPLIT_MODULESTORE
    DEFAULT_STATS = {
        'num_threads': 1,
        'num_comments': 1,
        'num_replies': 1,
        'num_upvotes': 1,
        'num_thread_followers': 1,
        'num_comments_generated': 1,
    }

    def setUp(self):
        super(StudentEngagementTests, self).setUp()
        self.user = UserFactory()
        self.user2 = UserFactory()
        self.user_ids = (self.user.id, self.user2.id)

        self._create_course()

        initialize_notifications()

    def _create_course(self, start=None, end=None):
        self.course = CourseFactory.create(
            start=start,
            end=end
        )

        CourseEnrollment.enroll(self.user, self.course.id)
        CourseEnrollment.enroll(self.user2, self.course.id)

    def test_no_engagment_records(self):
        """
        Verify that we get None back
        """

        self.assertIsNone(StudentSocialEngagementScore.get_user_engagement_score(self.course.id, self.user.id))
        self.assertIsNone(StudentSocialEngagementScore.get_user_engagement_score(self.course.id, self.user2.id))

        # no entries, means a rank of 0!
        result = StudentSocialEngagementScore.get_user_leaderboard_position(
            self.course.id,
            user_id=self.user.id
        )

        self.assertEqual(result['score'], 0)
        self.assertEqual(result['position'], 0)

        self.assertEqual(StudentSocialEngagementScore.generate_leaderboard(self.course.id)['total_user_count'], 0)

    def test_get_course_average_engagement_score(self):
        """
        Verify that average course engagement score is calculated correctly
        """
        self.assertEqual(StudentSocialEngagementScore.get_course_average_engagement_score(self.course.id), 0)
        StudentSocialEngagementScore.save_user_engagement_score(self.course.id, self.user.id, 100)
        self.assertEqual(StudentSocialEngagementScore.get_course_average_engagement_score(self.course.id), 50)
        StudentSocialEngagementScore.save_user_engagement_score(self.course.id, self.user2.id, 50)
        self.assertEqual(StudentSocialEngagementScore.get_course_average_engagement_score(self.course.id), 75)
        StudentSocialEngagementScore.save_user_engagement_score(self.course.id, self.user2.id, 150)
        self.assertEqual(StudentSocialEngagementScore.get_course_average_engagement_score(self.course.id), 125)

        # Exclude users from calculation:
        self.assertEqual(
            StudentSocialEngagementScore.get_course_average_engagement_score(
                self.course.id,
                exclude_users=[self.user.id],
            ),
            150
        )
        self.assertEqual(
            StudentSocialEngagementScore.get_course_average_engagement_score(
                self.course.id,
                exclude_users=[self.user2.id],
            ),
            100
        )
        self.assertEqual(
            StudentSocialEngagementScore.get_course_average_engagement_score(
                self.course.id,
                exclude_users=[self.user.id, self.user2.id],
            ),
            0
        )

    def test_get_course_engagement_scores(self):
        """
        Verify that scores for course are retrieved and excluded correctly.
        """
        expected_scores = {
            self.user.id: 100,
            self.user2.id: 150
        }

        for user_id, score in expected_scores.items():
            StudentSocialEngagementScore.save_user_engagement_score(self.course.id, user_id, score)

        scores = StudentSocialEngagementScore.get_course_engagement_scores(self.course.id)
        self.assertEqual(len(scores), 2)

        for user_id in expected_scores.keys():
            self.assertIn(user_id, scores)
            self.assertEqual(scores[user_id], expected_scores[user_id])

        # Check is excluding users works.
        scores = StudentSocialEngagementScore.get_course_engagement_scores(
            self.course.id,
            exclude_users=(self.user.id,))
        self.assertEqual(len(scores), 1)
        self.assertIn(self.user2.id, scores)

    def test_get_course_engagement_stats(self):
        """
        Verify that stats for course are complete.
        """
        StudentSocialEngagementScore.save_user_engagement_score(self.course.id, self.user.id, 100)
        StudentSocialEngagementScore.save_user_engagement_score(self.course.id, self.user2.id, 150)

        stats = StudentSocialEngagementScore.get_course_engagement_stats(self.course.id)
        self.assertEqual(len(stats), 2)

        for user_id in (self.user.id, self.user2.id):
            self.assertIn(user_id, stats)
            for key in stats[user_id].keys():
                self.assertTrue(key.startswith('num_'))

    def test_get_user_engagements_stats(self):
        """
        Verify that stats are complete.
        """
        StudentSocialEngagementScore.save_user_engagement_score(self.course.id, self.user.id, 100)
        stats = StudentSocialEngagementScore.get_user_engagements_stats(self.course.id, self.user.id)
        self.assertEqual(len(stats), 9)
        for key in stats.keys():
            self.assertTrue(key.startswith('num_'))

    def test_save_first_engagement_score(self):
        """
        Basic write operation
        """

        self.assertEqual(get_notifications_count_for_user(self.user.id), 0)

        StudentSocialEngagementScore.save_user_engagement_score(self.course.id, self.user.id, 10)

        # read it back
        self.assertEqual(
            StudentSocialEngagementScore.get_user_leaderboard_position(
                self.course.id,
                user_id=self.user.id
            )['score'],
            10
        )

        # confirm there is an entry in the History table
        self.assertEqual(
            StudentSocialEngagementScoreHistory.objects.filter(
                course_id=self.course.id,
                user__id=self.user.id
            ).count(),
            1
        )

        self.assertEqual(
            StudentSocialEngagementScore.get_user_leaderboard_position(
                self.course.id,
                user_id=self.user.id
            )['position'],
            1
        )

        # look at the leaderboard
        data = StudentSocialEngagementScore.generate_leaderboard(self.course.id)
        self.assertIsNotNone(data['queryset'])
        self.assertEqual(len(data['queryset']), 1)
        self.assertEqual(data['total_user_count'], 2)
        self.assertEqual(data['course_avg'], 5)

        self.assertEqual(data['queryset'][0].user.id, self.user.id)
        self.assertEqual(data['queryset'][0].score, 10)

        # confirm there is a notification was generated
        self.assertEqual(get_notifications_count_for_user(self.user.id), 1)

    def test_update_engagement_score(self):
        """
        Basic update operation
        """

        self.assertEqual(get_notifications_count_for_user(self.user.id), 0)

        StudentSocialEngagementScore.save_user_engagement_score(self.course.id, self.user.id, 10)

        # then update
        StudentSocialEngagementScore.save_user_engagement_score(self.course.id, self.user.id, 20)

        # read it back
        self.assertEqual(
            StudentSocialEngagementScore.get_user_leaderboard_position(
                self.course.id,
                user_id=self.user.id
            )['score'],
            20
        )

        # confirm there are two entries in the History table
        self.assertEqual(
            StudentSocialEngagementScoreHistory.objects.filter(
                course_id=self.course.id,
                user__id=self.user.id
            ).count(),
            2
        )

        self.assertEqual(
            StudentSocialEngagementScore.get_user_leaderboard_position(
                self.course.id,
                user_id=self.user.id
            )['position'],
            1
        )

        # look at the leaderboard
        data = StudentSocialEngagementScore.generate_leaderboard(self.course.id)
        self.assertIsNotNone(data['queryset'])
        self.assertEqual(len(data['queryset']), 1)
        self.assertEqual(data['total_user_count'], 2)
        self.assertEqual(data['course_avg'], 10)

        self.assertEqual(data['queryset'][0].user.id, self.user.id)
        self.assertEqual(data['queryset'][0].score, 20)

        # confirm there is a just a single notification was generated
        self.assertEqual(get_notifications_count_for_user(self.user.id), 1)

    def test_score_integrity(self):
        """
        Make sure we can't have duplicate course_id/user_id pais
        """

        StudentSocialEngagementScore.save_user_engagement_score(self.course.id, self.user.id, 10)

        again = StudentSocialEngagementScore(course_id=self.course.id, user_id=self.user.id, score=20)

        with self.assertRaises(IntegrityError):
            again.save()

    def test_update_user_engagement_score(self):
        """
        Run the engagement calculation for a user in a course
        """

        self.assertEqual(get_notifications_count_for_user(self.user.id), 0)

        with patch('social_engagement.engagement._get_course_social_stats') as mock_func:
            mock_func.return_value = ((self.user.id, self.DEFAULT_STATS),)
            update_course_engagement(self.course.id)

            leaderboard_position = StudentSocialEngagementScore.get_user_leaderboard_position(
                self.course.id,
                user_id=self.user.id
            )

            self.assertEqual(leaderboard_position['score'], 85)
            self.assertEqual(leaderboard_position['position'], 1)
            self.assertEqual(get_notifications_count_for_user(self.user.id), 1)

    def test_multiple_users(self):
        """
        See if it works with more than one enrollee
        """

        self.assertEqual(get_notifications_count_for_user(self.user.id), 0)
        self.assertEqual(get_notifications_count_for_user(self.user2.id), 0)

        stats = (
            self.DEFAULT_STATS,
            {
                'num_threads': 2,
                'num_comments': 2,
                'num_replies': 2,
                'num_upvotes': 2,
                'num_thread_followers': 2,
                'num_comments_generated': 2,
            }
        )

        with patch('social_engagement.engagement._get_course_social_stats') as mock_func:
            mock_func.return_value = zip(self.user_ids, stats)
            update_course_engagement(self.course.id)

        leaderboard_position = StudentSocialEngagementScore.get_user_leaderboard_position(
            self.course.id,
            user_id=self.user.id
        )

        self.assertEqual(leaderboard_position['score'], 85)

        # user should be in place #2
        self.assertEqual(leaderboard_position['position'], 2)
        self.assertEqual(get_notifications_count_for_user(self.user.id), 1)

        leaderboard_position = StudentSocialEngagementScore.get_user_leaderboard_position(
            self.course.id,
            user_id=self.user2.id
        )

        self.assertEqual(
            leaderboard_position['score'],
            170
        )

        # user2 should be in place #1
        self.assertEqual(
            leaderboard_position['position'],
            1
        )

        self.assertEqual(get_notifications_count_for_user(self.user2.id), 1)

    def test_calc_course(self):
        """
        Verifies that we can calculate the whole course enrollments
        """

        with patch('social_engagement.engagement._get_course_social_stats') as mock_func:
            mock_func.return_value = ((user_id, self.DEFAULT_STATS) for user_id in self.user_ids)
            # update whole course and re-calc
            update_course_engagement(self.course.id)

        data = StudentSocialEngagementScore.generate_leaderboard(self.course.id)

        self.assertEqual(len(data['queryset']), 2)

    @ddt.data(ModuleStoreEnum.Type.split, ModuleStoreEnum.Type.mongo)
    def test_all_courses(self, store):
        """
        Verifies that we can calculate over all courses
        """

        course2 = CourseFactory.create(org='foo', course='bar', run='baz', default_store=store)

        CourseEnrollment.enroll(self.user, course2.id)

        self.assertEqual(CourseEnrollment.objects.filter(course_id=course2.id).count(), 1)

        for course in (self.course, course2):
            with patch('social_engagement.engagement._get_course_social_stats') as mock_func:
                mock_func.return_value = ((user_id, self.DEFAULT_STATS) for user_id in self.user_ids)
                # update whole course and re-calc
                update_course_engagement(course.id)

        data = StudentSocialEngagementScore.generate_leaderboard(self.course.id)
        self.assertEqual(len(data['queryset']), 2)
        self.assertEqual(data['course_avg'], 85)

        data = StudentSocialEngagementScore.generate_leaderboard(course2.id)
        self.assertEqual(len(data['queryset']), 1)
        self.assertEqual(data['course_avg'], 85)

    @ddt.data(ModuleStoreEnum.Type.split, ModuleStoreEnum.Type.mongo)
    def test_closed_course(self, store):
        """
        Make sure we can force update closed course
        """

        course2 = CourseFactory.create(
            org='foo',
            course='bar',
            run='baz',
            end=datetime.now(pytz.UTC) - timedelta(days=1),
            default_store=store
        )

        CourseEnrollment.enroll(self.user, course2.id)
        CourseEnrollment.enroll(self.user2, course2.id)

        with patch('social_engagement.engagement._get_course_social_stats') as mock_func:
            mock_func.return_value = ((user_id, self.DEFAULT_STATS) for user_id in self.user_ids)
            # update whole course and re-calc
            update_course_engagement(course2.id, compute_if_closed_course=False)

            # shouldn't be anything in there because course is closed
            data = StudentSocialEngagementScore.generate_leaderboard(course2.id)
            self.assertEqual(len(data['queryset']), 0)
            self.assertEqual(data['course_avg'], 0)

            mock_func.return_value = ((user_id, self.DEFAULT_STATS) for user_id in self.user_ids)
            # update whole course and re-calc
            update_course_engagement(course2.id, compute_if_closed_course=True)

            # shouldn't be anything in there because course is closed
            data = StudentSocialEngagementScore.generate_leaderboard(course2.id)
            self.assertEqual(len(data['queryset']), 2)
            self.assertEqual(data['course_avg'], 85)

    def test_no_score(self):
        """
        Run the engagement calculation for a user in a course who has no score
        """

        self.assertEqual(get_notifications_count_for_user(self.user.id), 0)

        empty_stats = {
            'num_threads': 0,
            'num_comments': 0,
            'num_replies': 0,
            'num_upvotes': 0,
            'num_thread_followers': 0,
            'num_comments_generated': 0,
        }

        with patch('social_engagement.engagement._get_course_social_stats') as mock_func:
            mock_func.return_value = ((user_id, empty_stats) for user_id in self.user_ids)

            update_course_engagement(self.course.id, self.user.id)

            leaderboard_position = StudentSocialEngagementScore.get_user_leaderboard_position(
                self.course.id,
                user_id=self.user.id
            )

            self.assertEqual(
                leaderboard_position['score'],
                0
            )

            self.assertEqual(
                leaderboard_position['position'],
                0
            )

            self.assertEqual(get_notifications_count_for_user(self.user.id), 0)

    class MockResponse(object):
        pass

    class MockData(dict):
        def __init__(self, **kwargs):
            super(StudentEngagementTests.MockData, self).__init__(**kwargs)
            for key, value in kwargs.items():
                self[key] = value

        def __getattr__(self, item):
            return self.get(item)

    class MockSerializer(object):
        def __init__(self, user_id, flags):
            self.instance = {'user_id': user_id, 'abuse_flaggers': flags}

    def test_get_details_for_deletion(self):
        """
        Test getting comment stats that should be decremented.
        """
        comments = 3
        comment1_votes = 3
        comment1_votes2 = 30
        comment2_votes = 0

        expected = _detail_results_factory()
        expected['replies'] = comments
        expected['all_comments'] = comments
        expected['users'][self.user.id]['num_upvotes'] = comment1_votes + comment1_votes2
        expected['users'][self.user2.id]['num_upvotes'] = comment2_votes
        expected['users'][self.user.id]['num_comments'] = 2
        expected['users'][self.user2.id]['num_comments'] = 1
        expected['users'][self.user2.id]['num_flagged'] = 1

        mock_response = self.MockResponse()
        mock_response.data = {
            'pagination': {
                'count': comments,
                'next': None
            },
            'results': [
                self.MockData(**{
                    'vote_count': comment1_votes,
                    'child_count': 0,
                    'serializer': self.MockSerializer(self.user.id, 0),
                }),
                self.MockData(**{
                    'vote_count': comment1_votes2,
                    'child_count': 0,
                    'serializer': self.MockSerializer(self.user.id, 0),
                }),
                self.MockData(**{
                    'vote_count': comment2_votes,
                    'child_count': 0,
                    'serializer': self.MockSerializer(self.user2.id, 1),
                }),
            ],
        }

        with patch('social_engagement.engagement._get_request') as mock_func:
            mock_func.return_value = None
            with patch('lms.djangoapps.discussion_api.views.CommentViewSet.retrieve') as mock_func2:
                mock_func2.return_value = mock_response

                results = _get_details_for_deletion(None, None)
                self.assertEqual(results, expected)

    def test_get_details_for_deletion_with_replies(self):
        """
        Test getting stats of comment with nested comments.
        """
        comment_votes = 3

        expected = _detail_results_factory()
        expected['replies'] = 1
        expected['all_comments'] = 4
        expected['users'][self.user.id]['num_upvotes'] = comment_votes
        expected['users'][self.user2.id]['num_upvotes'] = 0
        expected['users'][self.user.id]['num_comments'] = 1
        expected['users'][self.user.id]['num_replies'] = 1
        expected['users'][self.user2.id]['num_replies'] = 2
        expected['users'][self.user2.id]['num_flagged'] = 2

        mock_response = self.MockResponse()
        mock_response.data = {
            'pagination': {
                'count': 1,
                'next': None
            },
            'results': [
                self.MockData(**{
                    'id': '1234',
                    'author': self.user.username,
                    'vote_count': comment_votes,
                    'child_count': 1,
                    'serializer': self.MockSerializer(self.user.id, 0),
                }),
            ],
        }

        mock_response2 = self.MockResponse()
        mock_response2.data = {
            'pagination': {
                'count': 3,
                'next': None
            },
            'results': [
                self.MockData(**{
                    'vote_count': 0,
                    'child_count': 0,
                    'serializer': self.MockSerializer(self.user.id, 0),
                }),
                self.MockData(**{
                    'vote_count': 0,
                    'child_count': 0,
                    'serializer': self.MockSerializer(self.user2.id, 1),
                }),
                self.MockData(**{
                    'vote_count': 0,
                    'child_count': 0,
                    'serializer': self.MockSerializer(self.user2.id, 1),
                }),
            ],
        }

        with patch('social_engagement.engagement._get_request') as mock_func:
            mock_func.return_value = None
            with patch('lms.djangoapps.discussion_api.views.CommentViewSet.retrieve') as mock_func2:
                mock_func2.side_effect = [mock_response, mock_response2]

                results = _get_details_for_deletion(None, None)
                self.assertEqual(results, expected)
