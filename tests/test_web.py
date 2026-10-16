"""The website's API, offline: the pipeline runs with the fake model on the synthetic recording."""
import threading
import time
import pytest
from fastapi.testclient import TestClient

from pipeline import run_pdd_pipeline
from tests.synthetic_video import build
from tests.template_fixture import build_template
from tests.test_pipeline import FakeLLM
from tests.test_template import FakeTemplateLLM, analysis_for_fixture
from web.app import create_app
from web.config import Settings
from web.db import Run, session


@pytest.fixture(scope="module")
def video(tmp_path_factory):
    path = tmp_path_factory.mktemp("video") / "synthetic.mp4"
    build(str(path))
    return path


def fake_run(video_path, run_dir, progress):
    llm = FakeLLM()
    return run_pdd_pipeline(video_path, run_dir, llm=llm, structure_llm=llm, transcribe=lambda v, audio_dir: [],
                            progress=progress)


def fake_template_run(video_path, run_dir, progress):
    llm = FakeTemplateLLM()
    return run_pdd_pipeline(video_path, run_dir, llm=llm, structure_llm=llm, transcribe=lambda v, audio_dir: [],
                            progress=progress)


def make_client(tmp_path, run_fn=fake_run, **settings) -> TestClient:
    s = Settings(data_dir=tmp_path / "data", frontend_dir=tmp_path / "no-frontend", **settings)
    return TestClient(create_app(s, run_fn=run_fn, analyze_template=lambda path: analysis_for_fixture()))


def register(client, email="ana@example.com", password="correct horse"):
    response = client.post("/api/auth/register", json={"email": email, "password": password})
    assert response.status_code == 201, response.text
    return response


def wait_for(client, run_id, statuses=("done", "failed"), timeout=120):
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] in statuses:
            return run
        time.sleep(0.2)
    raise AssertionError(f"run still {run['status']} after {timeout}s")


def upload(client, video, name="Invoice process.mp4"):
    with open(video, "rb") as f:
        return client.post("/api/runs", files={"file": (name, f, "video/mp4")})


def test_accounts(tmp_path):
    with make_client(tmp_path) as client:
        assert client.get("/api/auth/me").status_code == 401
        register(client, "Ana@Example.com ")
        assert client.get("/api/auth/me").json()["email"] == "ana@example.com"
        assert client.post("/api/auth/register", json={"email": "ana@example.com", "password": "x" * 8}).status_code == 409
        assert client.post("/api/auth/register", json={"email": "bo@example.com", "password": "short"}).status_code == 422
        assert client.post("/api/auth/register", json={"email": "not-an-email", "password": "x" * 8}).status_code == 422

        client.post("/api/auth/logout")
        assert client.get("/api/auth/me").status_code == 401
        assert client.post("/api/auth/login", json={"email": "ana@example.com", "password": "wrong pass"}).status_code == 401
        assert client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "whatever1"}).status_code == 401
        response = client.post("/api/auth/login", json={"email": "ana@example.com", "password": "correct horse"})
        assert response.status_code == 200
        cookie = response.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=lax" in cookie
        assert client.get("/api/auth/me").status_code == 200

        client.cookies.set("pdd_session", "forged.token.value")
        assert client.get("/api/auth/me").status_code == 401


def test_signup_can_be_limited(tmp_path):
    with make_client(tmp_path, signup_domains=["company.com"]) as client:
        assert client.post("/api/auth/register", json={"email": "x@gmail.com", "password": "x" * 8}).status_code == 403
        register(client, "x@company.com")
    with make_client(tmp_path / "closed", allow_signup=False) as client:
        assert client.post("/api/auth/register", json={"email": "x@company.com", "password": "x" * 8}).status_code == 403


def test_upload_to_document(tmp_path, video):
    with make_client(tmp_path) as client:
        assert upload(client, video).status_code == 401
        register(client)
        response = upload(client, video)
        assert response.status_code == 201, response.text
        run = wait_for(client, response.json()["id"])
        assert run["status"] == "done", run
        assert run["process_name"] == "Create invoice"
        assert run["summary"]["steps"] > 5 and run["summary"]["screenshots"] == run["summary"]["steps"] - 1
        assert any(w.startswith("Step 2 has no screenshot") for w in run["summary"]["warnings"])

        model = client.get(f"/api/runs/{run['id']}/model").json()
        assert "main_frame_path" not in model["as_is"][0]  # server paths aren't exposed
        image = client.get(model["as_is"][0]["image_url"])
        assert image.status_code == 200 and image.headers["content-type"] == "image/jpeg"

        doc = client.get(f"/api/runs/{run['id']}/document")
        assert doc.status_code == 200 and doc.content[:2] == b"PK"  # a .docx is a zip file
        assert "Create%20invoice%20-%20PDD.docx" in doc.headers["content-disposition"]

        assert [r["id"] for r in client.get("/api/runs").json()] == [run["id"]]
        assert client.delete(f"/api/runs/{run['id']}").status_code == 204
        assert client.get(f"/api/runs/{run['id']}").status_code == 404
        assert not (tmp_path / "data" / "runs" / run["id"]).exists()


def test_rejects_files_that_are_not_videos(tmp_path):
    with make_client(tmp_path) as client:
        register(client)
        assert client.post("/api/runs", files={"file": ("notes.txt", b"hello", "text/plain")}).status_code == 415
        assert client.post("/api/runs", files={"file": ("fake.mp4", b"not a video", "video/mp4")}).status_code == 415
        assert client.get("/api/runs").json() == []
        assert list((tmp_path / "data" / "runs").iterdir()) == []  # nothing left behind


def test_upload_size_limit(tmp_path):
    with make_client(tmp_path, max_upload_mb=1) as client:
        register(client)
        big = b"\0" * (1024 * 1024 + 1)
        assert client.post("/api/runs", files={"file": ("big.mp4", big, "video/mp4")}).status_code == 413


def test_users_only_see_their_own_runs(tmp_path, video):
    with make_client(tmp_path) as ana:
        bo = TestClient(ana.app)  # same server, separate browser (cookies)
        register(ana, "ana@example.com")
        run = wait_for(ana, upload(ana, video).json()["id"])
        register(bo, "bo@example.com")
        assert bo.get("/api/runs").json() == []
        for path in ("", "/model", "/frames/F001", "/document"):
            assert bo.get(f"/api/runs/{run['id']}{path}").status_code == 404
        assert bo.delete(f"/api/runs/{run['id']}").status_code == 404
        assert ana.get(f"/api/runs/{run['id']}/frames/..%2Fapp.db").status_code == 404


def test_failed_run_can_be_retried(tmp_path, video):
    attempts = []

    def flaky(video_path, run_dir, progress):
        attempts.append(run_dir)
        if len(attempts) == 1:
            raise RuntimeError("Error code: 429 - insufficient_quota")
        return fake_run(video_path, run_dir, progress)

    with make_client(tmp_path, run_fn=flaky) as client:
        register(client)
        run = wait_for(client, upload(client, video).json()["id"])
        assert run["status"] == "failed" and "ran out of credit" in run["error"]
        assert client.post(f"/api/runs/{run['id']}/retry").json()["status"] == "queued"
        assert wait_for(client, run["id"])["status"] == "done"
        assert attempts[0] == attempts[1]  # same folder, so finished stages are reused


def test_runs_interrupted_by_a_restart_continue(tmp_path, video):
    stuck = threading.Event()
    with make_client(tmp_path, run_fn=lambda *a: stuck.wait()) as client:
        register(client)
        run_id = upload(client, video).json()["id"]
        engine = client.app.state.engine
    # The server "stopped" while the run was in progress.
    with session(engine) as db:
        run = db.get(Run, run_id)
        run.status = "running"
        db.add(run)
        db.commit()
    with make_client(tmp_path) as client:
        client.post("/api/auth/login", json={"email": "ana@example.com", "password": "correct horse"})
        assert wait_for(client, run_id)["status"] == "done"


def test_serves_the_front_end(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<div id=root></div>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path / "secret.txt").write_text("secret")
    with TestClient(create_app(Settings(data_dir=tmp_path / "data", frontend_dir=dist), run_fn=fake_run)) as client:
        assert client.get("/runs/abc").text == "<div id=root></div>"  # app routes get the page
        assert client.get("/assets/app.js").text == "console.log(1)"
        assert client.get("/api/nothing").status_code == 404
        assert "secret" not in client.get("/..%2Fsecret.txt").text
        assert client.get("/").headers["x-frame-options"] == "DENY"


def test_templates(tmp_path, video):
    template = build_template(str(tmp_path / "Company PDD.docx"), str(tmp_path / "example.png"))
    with make_client(tmp_path, run_fn=fake_template_run) as client:
        register(client)
        assert client.post("/api/templates", files={"file": ("notes.txt", b"hi", "text/plain")}).status_code == 415
        assert client.post("/api/templates", files={"file": ("fake.docx", b"not a docx", "application/zip")}).status_code == 415
        with open(template, "rb") as f:
            response = client.post("/api/templates", files={"file": ("Company PDD.docx", f)})
        assert response.status_code == 201, response.text
        detail = response.json()
        assert detail["language"] == "Brazilian Portuguese" and detail["step_label"] == "P1 - "
        removed = {b["text"] for b in detail["blocks"] if b["action"] == "remove"}
        assert "Login SAP" in removed and "P1 - Realizar abertura do SAP 760" in removed
        assert [t["name"] for t in client.get("/api/templates").json()] == ["Company PDD.docx"]

        with open(video, "rb") as f:
            response = client.post("/api/runs", files={"file": ("Invoices.mp4", f, "video/mp4")},
                                   data={"template_id": detail["id"]})
        assert response.status_code == 201, response.text
        assert response.json()["stages"][0] == "analyze_template"
        run = wait_for(client, response.json()["id"])
        assert run["status"] == "done", run
        assert run["template_name"] == "Company PDD.docx"
        assert run["summary"]["to_complete"] >= 4
        assert any("highlighted in yellow" in w for w in run["summary"]["warnings"])

        # Deleting the template doesn't affect documents already made with it.
        assert client.delete(f"/api/templates/{detail['id']}").status_code == 204
        assert client.get(f"/api/templates/{detail['id']}").status_code == 404
        assert client.get(f"/api/runs/{run['id']}/document").status_code == 200

        # Other people can't see or use someone's template.
        with open(template, "rb") as f:
            mine = client.post("/api/templates", files={"file": ("Mine.docx", f)}).json()
        client.post("/api/auth/logout")
        register(client, "bo@example.com")
        assert client.get("/api/templates").json() == []
        assert client.get(f"/api/templates/{mine['id']}").status_code == 404
        with open(video, "rb") as f:
            response = client.post("/api/runs", files={"file": ("x.mp4", f, "video/mp4")},
                                   data={"template_id": mine["id"]})
        assert response.status_code == 404
