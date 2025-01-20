from django import forms

class AddSiteForm(forms.Form):
    domain = forms.CharField(label="도메인", max_length=255)
    name = forms.CharField(label="사이트 이름", max_length=255, required=False)
