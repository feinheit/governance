from django import forms
from django.test import SimpleTestCase

from governance.forms import Form


class TextareaRowsTest(SimpleTestCase):
    def test_small_unless_set(self):
        """Textareas grow with their text (autogrow.js), never below their
        rows: three instead of Django's ten, unless a form sets them"""

        class TextForm(Form):
            default = forms.CharField(widget=forms.Textarea)
            set = forms.CharField(widget=forms.Textarea(attrs={"rows": 12}))

        form = TextForm()
        self.assertIn('rows="3"', str(form["default"]))
        self.assertIn('rows="12"', str(form["set"]))
