"""Six bounded actual-JWT/auth.router/recovery HTTP scenarios on owned Mongo.
No protected helper imports, actual auth dependency, no dependency overrides.
Execution is paused only after actual route admission to retain a real intent.
"""
import asyncio
import json
from pathlib import Path
import uuid
import pytest
from motor.motor_asyncio import AsyncIOMotorClient

import bootstrap as qa

@pytest.fixture
def auth_case(request):
    def run(scenario):
        async def isolated():
            runtime, state = qa.verified_runtime()
            client = AsyncIOMotorClient(runtime.URI, serverSelectionTimeoutMS=2000,
                                        connectTimeoutMS=2000, socketTimeoutMS=4000)
            database = client["pd_boost03_auth_" + uuid.uuid4().hex]
            lane = qa.build_app(database)
            lane.events = []
            result = {"case": request.node.name, "db": database.name, "mongo_pid": state["pid"],
                      "actual_auth_dependency": True, "dependency_overrides": 0,
                      "source_hashes": qa.source_hashes(), "events": lane.events, "pass": False}
            try:
                await qa.seed(lane)
                await asyncio.wait_for(scenario(lane), timeout=35)
                result["pass"] = True
            finally:
                result["final_canonical_hash"] = qa.digest(await qa.snapshot(database))
                result["retained"] = True
                qa.exclusive_json(qa.HERE / (qa.RUN_TAG + "-" + request.node.name + ".json"), result)
                client.close()
        return asyncio.run(isolated())
    return run

async def prepare(lane, http, *, terminal=False):
    operation_id = str(uuid.uuid4())
    tokens = await qa.sign_tokens(lane)
    qa.set_session(http, tokens)
    if terminal:
        response = await qa.request(lane, http, "POST", "/api/orders/operations/create",
                                    payload=qa.command(operation_id))
        assert response.status_code == 201
        await qa.assert_effect(lane, operation_id)
    else:
        await qa.admit_pending(lane, http, operation_id)
    return operation_id, tokens

async def denied_recovery(lane, http, operation_id, status, code=None):
    before = await qa.snapshot(lane.database)
    path = "/api/orders/operations/create/" + operation_id
    for method, route, payload in (("GET", path, None), ("POST", path + "/resume", None),
                                   ("POST", "/api/orders/operations/create", qa.command(operation_id))):
        response = await qa.request(lane, http, method, route, payload=payload)
        assert response.status_code == status
        if code:
            assert response.json()["detail"]["code"] == code
    assert await qa.snapshot(lane.database) == before

def test_expired_cookie_blocks_fresh_bearer_and_owner_header(auth_case):
    async def scenario(lane):
        async with qa.client(lane) as http:
            operation_id, valid = await prepare(lane, http)
            expired = await qa.sign_tokens(lane, expired_access=True)
            qa.set_session(http, expired)
            before = await qa.snapshot(lane.database)
            me = await qa.request(lane, http, "GET", "/api/auth/me", bearer=valid["access"])
            assert me.status_code == 401 and me.json()["detail"] == "Token expired"
            # A comparative header and fresh bearer cannot rescue an expired priority cookie.
            original = lane.operations.db
            lane.operations.db = qa.ForbiddenDatabase()
            try:
                for method, path in (("GET", "/api/orders/operations/create/" + operation_id),
                                     ("POST", "/api/orders/operations/create/" + operation_id + "/resume"),
                                     ("GET", "/api/orders/operations/create/capabilities")):
                    response = await qa.request(lane, http, method, path, bearer=valid["access"])
                    assert response.status_code == 401
                    qa.assert_private_free(response, (valid["access"], expired["access"], expired["refresh"]))
                http.cookies.clear()
                response = await qa.request(lane, http, "GET", "/api/auth/me")
                assert response.status_code == 401
            finally:
                lane.operations.db = original
            assert await qa.snapshot(lane.database) == before
    auth_case(scenario)

def test_actual_refresh_rotates_access_then_bodyless_resume_exactly_once(auth_case):
    async def scenario(lane):
        async with qa.client(lane) as http:
            operation_id, _ = await prepare(lane, http)
            expired = await qa.sign_tokens(lane, expired_access=True)
            qa.set_session(http, expired)
            before = await qa.snapshot(lane.database)
            me = await qa.request(lane, http, "GET", "/api/auth/me")
            assert me.status_code == 401
            refreshed = await qa.request(lane, http, "POST", "/api/auth/refresh", expected=None)
            assert refreshed.status_code == 200 and refreshed.json()["user"]["id"] == qa.OWNER
            headers = refreshed.headers.get_list("set-cookie")
            assert len(headers) == 2 and all("HttpOnly" in value and "SameSite=lax" in value and "Path=/" in value for value in headers)
            assert http.cookies.get("access_token") != expired["access"]
            assert lane.auth.decode_token(http.cookies.get("access_token"), "access")["user_id"] == qa.OWNER
            assert http.cookies.get("refresh_token") == expired["refresh"], "Existing refresh token is retained by actual endpoint"
            me = await qa.request(lane, http, "GET", "/api/auth/me")
            assert me.status_code == 200 and me.json()["id"] == qa.OWNER
            assert await qa.snapshot(lane.database) == before
            await qa.recover_once(lane, http, operation_id)
            assert (await lane.database.counters.find_one({"_id": "orders.global"}))["seq"] == 101
    auth_case(scenario)

def test_refresh_denials_keep_pending_and_terminal_ledger_unchanged(auth_case):
    async def scenario(lane):
        async with qa.client(lane) as http:
            pending_id, valid = await prepare(lane, http)
            terminal_id, _ = await prepare(lane, http, terminal=True)
            expired = await qa.sign_tokens(lane, expired_access=True, expired_refresh=True)
            wrong_key = lane.auth.jwt.encode({"user_id": qa.OWNER, "type": "refresh", "exp": 4102444800},
                                             "qa-only-wrong-auth03-key-for-negative-case", algorithm="HS256")
            variants = (("expired", expired["refresh"]), ("wrong-type", valid["access"]),
                        ("bad-signature", wrong_key), ("missing", None))
            before = await qa.snapshot(lane.database)
            for label, refresh in variants:
                qa.set_session(http, {"access": expired["access"], "refresh": refresh})
                response = await qa.request(lane, http, "POST", "/api/auth/refresh", expected=None)
                assert response.status_code == 401 and not response.headers.get_list("set-cookie")
                assert "token" not in response.json()
                await denied_recovery(lane, http, pending_id, 401)
                await denied_recovery(lane, http, terminal_id, 401)
            assert await qa.snapshot(lane.database) == before
            # Terminal receipt remains available after explicit matching-session restoration.
            qa.set_session(http, valid)
            lookup = await qa.request(lane, http, "GET", "/api/orders/operations/create/" + terminal_id)
            assert lookup.status_code == 200 and lookup.json()["state"] == "replayed"
            assert await qa.snapshot(lane.database) == before
    auth_case(scenario)

def test_disabled_user_blocks_me_refresh_and_both_ledger_states(auth_case):
    async def scenario(lane):
        async with qa.client(lane) as http:
            pending_id, valid = await prepare(lane, http)
            terminal_id, _ = await prepare(lane, http, terminal=True)
            await lane.database.users.update_one({"id": qa.OWNER}, {"$set": {"account_disabled": True}})
            before = await qa.snapshot(lane.database)
            for method, path in (("GET", "/api/auth/me"), ("POST", "/api/auth/refresh")):
                response = await qa.request(lane, http, method, path, expected=None)
                assert response.status_code == 403 and not response.headers.get_list("set-cookie")
            await denied_recovery(lane, http, pending_id, 403)
            await denied_recovery(lane, http, terminal_id, 403)
            assert await qa.snapshot(lane.database) == before
            await lane.database.users.update_one({"id": qa.OWNER}, {"$set": {"account_disabled": False}})
            # Actual login, rather than a substituted dependency, restores the same eligible identity.
            login = await qa.request(lane, http, "POST", "/api/auth/login", expected=None,
                                     payload={"email": qa.OWNER + "@example.invalid", "password": qa.QA_PASSWORD})
            assert login.status_code == 200 and login.json()["user"]["id"] == qa.OWNER
            await qa.recover_once(lane, http, pending_id)
            assert (await lane.database.counters.find_one({"_id": "orders.global"}))["seq"] == 102
    auth_case(scenario)

def test_same_id_new_db_role_does_not_inherit_old_role_ledger(auth_case):
    async def scenario(lane):
        async with qa.client(lane) as http:
            pending_id, _ = await prepare(lane, http)
            terminal_id, _ = await prepare(lane, http, terminal=True)
            await lane.database.users.update_one({"id": qa.OWNER}, {"$set": {"role": "admin"}})
            before = await qa.snapshot(lane.database)
            for method, path in (("GET", "/api/auth/me"), ("POST", "/api/auth/refresh")):
                response = await qa.request(lane, http, method, path, expected=None)
                assert response.status_code == 200
                actor = response.json() if method == "GET" else response.json()["user"]
                assert actor["id"] == qa.OWNER and actor["role"] == "admin"
            await denied_recovery(lane, http, pending_id, 403, "AUTH_CONTEXT_CHANGED")
            await denied_recovery(lane, http, terminal_id, 403, "AUTH_CONTEXT_CHANGED")
            assert await qa.snapshot(lane.database) == before
            await lane.database.users.update_one({"id": qa.OWNER}, {"$set": {"role": "restaurant"}})
            response = await qa.request(lane, http, "POST", "/api/auth/refresh", expected=None)
            assert response.status_code == 200 and response.json()["user"]["role"] == "restaurant"
            await qa.recover_once(lane, http, pending_id)
    auth_case(scenario)

def test_same_id_new_restaurant_binding_and_comparative_header_are_separate(auth_case):
    async def scenario(lane):
        async with qa.client(lane) as http:
            pending_id, _ = await prepare(lane, http)
            terminal_id, _ = await prepare(lane, http, terminal=True)
            await lane.database.users.update_one({"id": qa.OWNER}, {"$set": {"restaurant_id": qa.RESTAURANT_OTHER}})
            before = await qa.snapshot(lane.database)
            me = await qa.request(lane, http, "GET", "/api/auth/me")
            assert me.status_code == 200 and me.json()["id"] == qa.OWNER
            assert me.json()["restaurant_id"] == qa.RESTAURANT_OTHER
            refresh = await qa.request(lane, http, "POST", "/api/auth/refresh", expected=None)
            assert refresh.status_code == 200 and refresh.json()["user"]["restaurant_id"] == qa.RESTAURANT_OTHER
            await denied_recovery(lane, http, pending_id, 403, "NOT_AUTHORIZED")
            await denied_recovery(lane, http, terminal_id, 403, "NOT_AUTHORIZED")
            assert await qa.snapshot(lane.database) == before
            original = lane.operations.db
            lane.operations.db = qa.ForbiddenDatabase()
            try:
                response = await qa.request(lane, http, "GET", "/api/orders/operations/create/" + pending_id,
                                            expected=qa.OTHER)
                assert response.status_code == 403 and response.json()["detail"]["code"] == "AUTH_CONTEXT_CHANGED"
            finally:
                lane.operations.db = original
            assert await qa.snapshot(lane.database) == before
            await lane.database.users.update_one({"id": qa.OWNER}, {"$set": {"restaurant_id": qa.RESTAURANT}})
            refreshed = await qa.request(lane, http, "POST", "/api/auth/refresh", expected=None)
            assert refreshed.status_code == 200 and refreshed.json()["user"]["restaurant_id"] == qa.RESTAURANT
            await qa.recover_once(lane, http, pending_id)
    auth_case(scenario)
