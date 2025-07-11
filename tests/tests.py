import datetime
import os
import unittest
import warnings
from io import StringIO

from django import http
from django.core.files.uploadedfile import (
    InMemoryUploadedFile, TemporaryUploadedFile,
)
from django.test import TestCase, override_settings

from formtools import preview, utils

from .forms import (
    HashTestBlankForm, HashTestForm, HashTestFormWithFile, ManyModel,
    OtherModelForm, TestForm,
)

success_string = "Done was called!"
success_string_encoded = success_string.encode()


class TestFormPreview(preview.FormPreview):
    def parse_params(self, request, *args, **kwargs):
        self.state['user'] = request.user

    def get_context(self, request, form):
        context = super().get_context(request, form)
        context.update({'custom_context': True})
        return context

    def get_initial(self, request):
        return {'field1': 'Works!'}

    def done(self, request, cleaned_data):
        return http.HttpResponse(success_string)


@override_settings(
    TEMPLATES=[{
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(os.path.dirname(__file__), 'templates')],
        'APP_DIRS': True,
    }],
    ROOT_URLCONF='tests.urls',
)
class PreviewTests(TestCase):

    def setUp(self):
        super().setUp()
        # Create a FormPreview instance to share between tests
        self.preview = preview.FormPreview(TestForm)
        input_template = '<input type="hidden" name="%s" value="%s" />'
        self.input = input_template % (self.preview.unused_name('stage'), "%d")
        self.test_data = {'field1': 'foo', 'field1_': 'asdf'}

    def test_parse_params_takes_request_object(self):
        """
        FormPreview.parse_params takes a request object as the first argument.
        """
        response = self.client.get('/preview/')
        state = response.context['state']
        self.assertIsNotNone(state.get('user') is not None)

    def test_unused_name(self):
        """
        Verifies name mangling to get uniue field name.
        """
        self.assertEqual(self.preview.unused_name('field1'), 'field1__')

    def test_form_get(self):
        """
        Test formtools.preview form retrieval.

        Use the client library to see if we can successfully retrieve
        the form (mostly testing the setup ROOT_URLCONF
        process). Verify that an additional  hidden input field
        is created to manage the stage.

        """
        response = self.client.get('/preview/')
        stage = self.input % 1
        self.assertContains(response, stage, 1)
        self.assertEqual(response.context['custom_context'], True)
        self.assertEqual(response.context['form'].initial, {'field1': 'Works!'})

    def test_form_preview(self):
        """
        Test formtools.preview form preview rendering.

        Use the client library to POST to the form to see if a preview
        is returned.  If we do get a form back check that the hidden
        value is correctly managing the state of the form.

        """
        # Pass strings for form submittal and add stage variable to
        # show we previously saw first stage of the form.
        self.test_data.update({'stage': 1, 'date1': datetime.date(2006, 10, 25)})
        response = self.client.post('/preview/', self.test_data)
        # Check to confirm stage is set to 2 in output form.
        stage = self.input % 2
        self.assertContains(response, stage, 1)

    def test_form_submit(self):
        """
        Test formtools.preview form submittal.

        Use the client library to POST to the form with stage set to 3
        to see if our forms done() method is called. Check first
        without the security hash, verify failure, retry with security
        hash and verify success.

        """
        # Pass strings for form submittal and add stage variable to
        # show we previously saw first stage of the form.
        self.test_data.update({'stage': 2, 'date1': datetime.date(2006, 10, 25)})
        response = self.client.post('/preview/', self.test_data)
        self.assertNotEqual(response.content, success_string_encoded)
        hash = self.preview.security_hash(None, TestForm(self.test_data))
        self.test_data.update({'hash': hash})
        response = self.client.post('/preview/', self.test_data)
        self.assertEqual(response.content, success_string_encoded)

    def test_bool_submit(self):
        """
        Test formtools.preview form submittal when form contains:
        BooleanField(required=False)

        Ticket: #6209 - When an unchecked BooleanField is previewed, the preview
        form's hash would be computed with no value for ``bool1``. However, when
        the preview form is rendered, the unchecked hidden BooleanField would be
        rendered with the string value 'False'. So when the preview form is
        resubmitted, the hash would be computed with the value 'False' for
        ``bool1``. We need to make sure the hashes are the same in both cases.

        """
        self.test_data.update({'stage': 2})
        hash = self.preview.security_hash(None, TestForm(self.test_data))
        self.test_data.update({'hash': hash, 'bool1': 'False'})
        with warnings.catch_warnings(record=True):
            response = self.client.post('/preview/', self.test_data)
            self.assertEqual(response.content, success_string_encoded)

    def test_form_submit_good_hash(self):
        """
        Test formtools.preview form submittal, using a correct
        hash
        """
        # Pass strings for form submittal and add stage variable to
        # show we previously saw first stage of the form.
        self.test_data.update({'stage': 2})
        response = self.client.post('/preview/', self.test_data)
        self.assertNotEqual(response.content, success_string_encoded)
        hash = utils.form_hmac(TestForm(self.test_data))
        self.test_data.update({'hash': hash})
        response = self.client.post('/preview/', self.test_data)
        self.assertEqual(response.content, success_string_encoded)

    def test_form_submit_bad_hash(self):
        """
        Test formtools.preview form submittal does not proceed
        if the hash is incorrect.
        """
        # Pass strings for form submittal and add stage variable to
        # show we previously saw first stage of the form.
        self.test_data.update({'stage': 2})
        response = self.client.post('/preview/', self.test_data)
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response.content, success_string_encoded)
        hash = utils.form_hmac(TestForm(self.test_data)) + "bad"
        self.test_data.update({'hash': hash})
        response = self.client.post('/previewpreview/', self.test_data)
        self.assertNotEqual(response.content, success_string_encoded)


class FormHmacTests(unittest.TestCase):

    def test_textfield_hash(self):
        """
        Regression test for #10034: the hash generation function should ignore
        leading/trailing whitespace so as to be friendly to broken browsers that
        submit it (usually in textareas).
        """
        f1 = HashTestForm({'name': 'joe', 'bio': 'Speaking español.'})
        f2 = HashTestForm({'name': '  joe', 'bio': 'Speaking español.  '})
        hash1 = utils.form_hmac(f1)
        hash2 = utils.form_hmac(f2)
        self.assertEqual(hash1, hash2)

    def test_empty_permitted(self):
        """
        Regression test for #10643: the security hash should allow forms with
        empty_permitted = True, or forms where data has not changed.
        """
        f1 = HashTestBlankForm({})
        f2 = HashTestForm({}, empty_permitted=True, use_required_attribute=False)
        hash1 = utils.form_hmac(f1)
        hash2 = utils.form_hmac(f2)
        self.assertEqual(hash1, hash2)

    def test_hash_with_file(self):
        with InMemoryUploadedFile(StringIO('1'), '', 'test', 'text/plain', 1, 'utf8') as some_file:
            f1 = HashTestFormWithFile({'name': 'joe'})
            f2 = HashTestFormWithFile({'name': 'joe'}, files={'attachment': some_file})
            hash1 = utils.form_hmac(f1)
            hash2 = utils.form_hmac(f2)
        self.assertNotEqual(hash1, hash2)

        with TemporaryUploadedFile('test', 'text/plain', 1, 'utf8') as some_file:
            some_file.write(b'1')
            some_file.seek(0)
            f1 = HashTestFormWithFile({'name': 'joe'})
            f2 = HashTestFormWithFile({'name': 'joe'}, files={'attachment': some_file})
            hash1 = utils.form_hmac(f1)
            hash2 = utils.form_hmac(f2)
        self.assertNotEqual(hash1, hash2)


class PicklingTests(unittest.TestCase):

    def setUp(self):
        super().setUp()
        ManyModel.objects.create(name="jane")

    def test_queryset_hash(self):
        """
        Regression test for #10034: the hash generation function should ignore
        leading/trailing whitespace so as to be friendly to broken browsers that
        submit it (usually in textareas).
        """

        qs1 = ManyModel.objects.all()
        qs2 = ManyModel.objects.all()

        qs1._prefetch_done = True
        qs2._prefetch_done = False
        f1 = OtherModelForm({'name': 'joe', 'manymodels': qs1})
        f2 = OtherModelForm({'name': 'joe', 'manymodels': qs2})
        hash1 = utils.form_hmac(f1)
        hash2 = utils.form_hmac(f2)
        self.assertEqual(hash1, hash2)
