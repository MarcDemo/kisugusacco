from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from groupcore.models import MemberProfile
from .models import Fine


class FineManagementTests(TestCase):
    def setUp(self):
        self.treasurer = MemberProfile.objects.create_user(
            username='treasurer',
            password='pass12345',
            role='TREASURER',
        )
        self.member = MemberProfile.objects.create_user(
            username='member',
            password='pass12345',
            role='MEMBER',
        )
        self.fine = Fine.objects.create(
            member=self.member,
            reason='Manual fine',
            amount=Decimal('2000.00'),
            issued_by=self.treasurer,
        )

    def test_treasurer_can_delete_fine(self):
        self.client.login(username='treasurer', password='pass12345')

        response = self.client.post(reverse('delete_fine', args=[self.fine.id]))

        self.assertRedirects(response, reverse('manage_fines'))
        self.assertFalse(Fine.objects.filter(id=self.fine.id).exists())

    def test_non_treasurer_cannot_delete_fine(self):
        self.client.login(username='member', password='pass12345')

        response = self.client.post(reverse('delete_fine', args=[self.fine.id]))

        self.assertRedirects(response, reverse('member_dashboard'))
        self.assertTrue(Fine.objects.filter(id=self.fine.id).exists())
