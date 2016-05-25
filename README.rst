discussion-edx-platform-extensions
==================================

discussion-edx-platform-extensions (``social_engagement``) is a Django application responsible to compute and persist user's social score per course based on activity in the forums.


Open edX Platform Integration
-----------------------------
1. Update the version of ``discussion-edx-platform-extensions`` in the appropriate requirements file (e.g. ``requirements/edx/custom.txt``).
2. Add ``social_engagement`` to the list of installed apps in ``common.py``.
3. Set following feature flag in ``common.py``.

.. code-block:: bash

  'ENABLE_SOCIAL_ENGAGEMENT': True

4. Install social_engagement app via requirements file.

.. code-block:: bash

  $ pip install -r requirements/edx/custom.txt

5. (Optional) Run tests:

.. code-block:: bash

   $ python manage.py lms --settings test test social_engagement.tests

