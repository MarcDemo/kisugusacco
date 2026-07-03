from django import forms
from .models import Expenditure, Asset

class ExpenditureForm(forms.ModelForm):
    class Meta:
        model = Expenditure
        fields = ['description', 'amount', 'source', 'remarks']

class AssetForm(forms.ModelForm):
    class Meta:
        model = Asset
        fields = ['name', 'value', 'date_acquired', 'source', 'remarks']
        widgets = {
            'date_acquired': forms.DateInput(attrs={'type': 'date'}),
        }