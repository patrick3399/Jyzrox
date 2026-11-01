"""Schema contract for egress personas (ADR 0022)."""

import pytest
from sqlalchemy.exc import IntegrityError

from db.models import Credential, EgressPersona, PersonaAccount


async def _cred(session, source: str, account: str) -> None:
    session.add(Credential(source=source, account=account, credential_type="cookies", is_active=False))
    await session.commit()


async def test_one_credential_account_cannot_be_bound_to_two_personas(db_session):
    await _cred(db_session, "twitter", "alt1")
    a = EgressPersona(name="gw11", proxy_url="http://egress-11:8888")
    b = EgressPersona(name="gw12", proxy_url="http://egress-12:8888")
    db_session.add_all([a, b])
    await db_session.commit()

    db_session.add(PersonaAccount(persona_id=a.id, source="twitter", account="alt1"))
    await db_session.commit()
    db_session.add(PersonaAccount(persona_id=b.id, source="twitter", account="alt1"))
    with pytest.raises(IntegrityError):
        await db_session.commit()


async def test_persona_holds_at_most_one_account_per_site(db_session):
    await _cred(db_session, "twitter", "alt1")
    await _cred(db_session, "twitter", "alt2")
    p = EgressPersona(name="gw13", proxy_url=None)
    db_session.add(p)
    await db_session.commit()
    db_session.add(PersonaAccount(persona_id=p.id, source="twitter", account="alt1"))
    await db_session.commit()
    db_session.add(PersonaAccount(persona_id=p.id, source="twitter", account="alt2"))
    with pytest.raises(IntegrityError):
        await db_session.commit()
