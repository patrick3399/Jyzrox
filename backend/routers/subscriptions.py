"""Subscription management endpoints."""

from fastapi import APIRouter

from . import subscriptions_actions, subscriptions_create, subscriptions_list, subscriptions_manage
from .subscriptions_create import CreateSubscriptionRequest as CreateSubscriptionRequest
from .subscriptions_manage import BulkMoveRequest as BulkMoveRequest
from .subscriptions_manage import PatchSubscriptionRequest as PatchSubscriptionRequest
from .subscriptions_manage import delete_subscription as delete_subscription

router = APIRouter(tags=["subscriptions"])

router.include_router(subscriptions_list.router)
router.include_router(subscriptions_create.router)
router.include_router(subscriptions_manage.router)
router.include_router(subscriptions_actions.router)
