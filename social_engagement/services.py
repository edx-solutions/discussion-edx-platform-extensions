from xml.sax import saxutils


class DiscussionService(object):
    """
    This is a temporary service that provides everything needed to render the discussion template.

    Used by xblock-discussion
    """

    def __init__(self, runtime):
        self.runtime = runtime

    def get_course_template_context(self):
        """
        Returns the context to render the course-level discussion templates.

        """
        # for some reason pylint reports courseware.access, courseware.courses and django_comment_client.forum.views
        # pylint: disable=import-error
        import json
        from django.conf import settings
        from django.http import HttpRequest
        import lms.lib.comment_client as cc
        from courseware.access import has_access
        from courseware.courses import get_course_with_access
        from django_comment_client.permissions import has_permission
        from django_comment_client.forum.views import get_threads, make_course_settings
        import django_comment_client.utils as utils
        from openedx.core.djangoapps.course_groups.cohorts import (
            is_course_cohorted,
            get_cohort_id,
            get_cohorted_commentables,
            get_course_cohorts
        )

        escapedict = {'"': '&quot;'}

        request = HttpRequest()
        user = self.runtime.user
        request.user = user
        user_info = cc.User.from_django_user(self.runtime.user).to_dict()
        course_id = self.runtime.course_id
        course = get_course_with_access(self.runtime.user, 'load', course_id, check_if_enrolled=True)
        user_cohort_id = get_cohort_id(user, course_id)

        unsafethreads, query_params = get_threads(request, course)
        threads = [utils.prepare_content(thread, course_id) for thread in unsafethreads]
        utils.add_courseware_context(threads, course, user)

        flag_moderator = has_permission(user, 'openclose_thread', course_id) or has_access(user, 'staff', course)

        annotated_content_info = utils.get_metadata_for_threads(course_id, threads, user, user_info)
        category_map = utils.get_discussion_category_map(course, user)

        cohorts = [{"id": str(g.id), "name": g.name} for g in get_course_cohorts(course)]
        cohorted_commentables = get_cohorted_commentables(course_id)

        course_settings = make_course_settings(course, user)

        context = {
            'user': user,
            'settings': settings,
            'course': course,
            'course_id': course_id,
            'staff_access': has_access(user, 'staff', course),
            'threads': saxutils.escape(json.dumps(threads), escapedict),
            'thread_pages': query_params['num_pages'],
            'user_info': saxutils.escape(json.dumps(user_info), escapedict),
            'flag_moderator': flag_moderator,
            'annotated_content_info': saxutils.escape(json.dumps(annotated_content_info), escapedict),
            'category_map': category_map,
            'roles': saxutils.escape(json.dumps(utils.get_role_ids(course_id)), escapedict),
            'is_moderator': has_permission(user, "see_all_cohorts", course_id),
            'cohorts': cohorts,
            'user_cohort': user_cohort_id,
            'sort_preference': user_info['default_sort_key'],
            'cohorted_commentables': cohorted_commentables,
            'is_course_cohorted': is_course_cohorted(course_id),
            'has_permission_to_create_thread': has_permission(user, "create_thread", course_id),
            'has_permission_to_create_comment': has_permission(user, "create_comment", course_id),
            'has_permission_to_create_subcomment': has_permission(user, "create_subcomment", course_id),
            'has_permission_to_openclose_thread': has_permission(user, "openclose_thread", course_id),
            'course_settings': saxutils.escape(json.dumps(course_settings), escapedict),
        }

        return context

    def get_inline_template_context(self):
        """
        Returns the context to render inline discussion templates.
        """
        # for some reason pylint reports courseware.access, courseware.courses and django_comment_client.forum.views
        # pylint: disable=import-error
        from django.conf import settings
        from courseware.courses import get_course_with_access
        from courseware.access import has_access
        from django_comment_client.permissions import has_permission
        from django_comment_client.utils import get_discussion_category_map

        course_id = self.runtime.course_id
        user = self.runtime.user

        course = get_course_with_access(user, 'load', course_id, check_if_enrolled=True)
        category_map = get_discussion_category_map(course, user)

        is_moderator = has_permission(user, "see_all_cohorts", course_id)
        flag_moderator = has_permission(user, 'openclose_thread', course_id) or has_access(user, 'staff', course)

        context = {
            'user': user,
            'settings': settings,
            'course': course,
            'category_map': category_map,
            'is_moderator': is_moderator,
            'flag_moderator': flag_moderator,
            'has_permission_to_create_thread': has_permission(user, "create_thread", course_id),
            'has_permission_to_create_comment': has_permission(user, "create_comment", course_id),
            'has_permission_to_create_subcomment': has_permission(user, "create_subcomment", course_id),
            'has_permission_to_openclose_thread': has_permission(user, "openclose_thread", course_id)
        }

        return context
