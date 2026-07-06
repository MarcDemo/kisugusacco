from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from .models import Expenditure, Asset
from .forms import ExpenditureForm, AssetForm
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from deposits.models import DepositSubmission
from incomes.models import OtherIncome 
from decimal import Decimal

# Create your views here.


SOURCE_FIELD_MAP = {
    'SAVINGS': 'saving_amount',
    'WELFARE': 'welfare_amount',
    'FINES': 'fine_amount',
    'ANNUAL_SUBSCRIPTIONS': 'annual_subscription_amount',
    'MEMBERSHIP': 'membership_amount',
    'SHARES': 'shares_amount',
}

def get_current_balances():
    approved = DepositSubmission.objects.filter(status='APPROVED')
    balances = {}

    for source, field_name in SOURCE_FIELD_MAP.items():
        collected = Decimal(approved.aggregate(total=Sum(field_name))['total'] or 0)
        expenditures = Decimal(Expenditure.objects.filter(source=source).aggregate(total=Sum('amount'))['total'] or 0)
        assets = Decimal(Asset.objects.filter(source=source).aggregate(total=Sum('value'))['total'] or 0)
        balances[source] = {
            'collected': collected,
            'available': collected - expenditures - assets,
        }

    return balances
# 📦 View Assets
@login_required
def list_assets(request):
    if not request.user.is_treasurer():
        messages.error(request, "Access denied.")
        return redirect('member_dashboard')

    assets = Asset.objects.order_by('-date_acquired')
    total_assets = assets.aggregate(Sum('value'))['value__sum'] or 0

    return render(request, 'Assets_Expenditures/assets_list.html', {
        'assets': assets,
        'total_assets': total_assets,
    })


# ➕ Add Asset
@login_required
def add_asset(request):
    if not request.user.is_treasurer():
        messages.error(request, "Access denied.")
        return redirect('member_dashboard')

    if request.method == 'POST':
        form = AssetForm(request.POST)
        if form.is_valid():
            asset = form.save()
            messages.success(request, f"Asset '{asset.name}' added successfully.")
            return redirect('list_assets')
    else:
        form = AssetForm()

    balances = get_current_balances()

    return render(request, 'Assets_Expenditures/add_asset.html', {
        'form': form,
        'available_balances': balances,
    })


# 💸 View Expenditures
@login_required
def list_expenditures(request):
    if not request.user.is_treasurer():
        messages.error(request, "Access denied.")
        return redirect('member_dashboard')

    expenditures = Expenditure.objects.order_by('-date_spent')
    total_expenditures = expenditures.aggregate(Sum('amount'))['amount__sum'] or 0

    return render(request, 'Assets_Expenditures/expenditures_list.html', {
        'expenditures': expenditures,
        'total_expenditures': total_expenditures,
    })


# ➕ Add Expenditure
@login_required
def add_expenditure(request):
    if not request.user.is_treasurer():
        messages.error(request, "Access denied.")
        return redirect('member_dashboard')

    if request.method == 'POST':
        form = ExpenditureForm(request.POST)
        if form.is_valid():
            expenditure = form.save()
            messages.success(request, f"Expenditure '{expenditure.description}' added successfully.")
            return redirect('list_expenditures')
    else:
        form = ExpenditureForm()

    balances = get_current_balances()

    return render(request, 'Assets_Expenditures/add_expenditure.html', {
        'form': form,
        'available_balances': balances,
    })
