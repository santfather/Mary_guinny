from __future__ import annotations

import uuid


def test_approve_is_idempotent_and_sets_timestamp(
    api_client, project_id, character_id, make_reference
) -> None:
    asset_id = make_reference(project_id=project_id, character_id=character_id)
    before = api_client.get(f"/api/reference-assets/{asset_id}").json()
    assert before["status"] == "draft"
    assert before["approved_at"] is None

    response = api_client.post(f"/api/reference-assets/{asset_id}/approve")
    assert response.status_code == 200
    approved = response.json()
    assert approved["status"] == "approved"
    assert approved["approved_at"] is not None
    assert approved["sha256"] == before["sha256"]
    assert approved["content_url"] == before["content_url"]

    repeated = api_client.post(f"/api/reference-assets/{asset_id}/approve")
    assert repeated.status_code == 200
    assert repeated.json()["approved_at"] == approved["approved_at"]


def test_reject_draft_and_approved(
    api_client, project_id, character_id, make_reference
) -> None:
    draft_id = make_reference(project_id=project_id, character_id=character_id)
    rejected = api_client.post(f"/api/reference-assets/{draft_id}/reject")
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["approved_at"] is None

    approved_id = make_reference(
        project_id=project_id, character_id=character_id, status="approved"
    )
    downgraded = api_client.post(f"/api/reference-assets/{approved_id}/reject")
    assert downgraded.status_code == 200
    assert downgraded.json()["status"] == "rejected"

    restored = api_client.post(f"/api/reference-assets/{approved_id}/approve")
    assert restored.status_code == 200
    assert restored.json()["status"] == "approved"


def test_superseded_reference_cannot_be_reviewed(
    api_client, project_id, character_id, make_reference
) -> None:
    asset_id = make_reference(
        project_id=project_id, character_id=character_id, status="superseded"
    )
    assert api_client.post(f"/api/reference-assets/{asset_id}/approve").status_code == 409
    assert api_client.post(f"/api/reference-assets/{asset_id}/reject").status_code == 409


def test_approved_row_is_immutable(
    api_client, project_id, character_id, make_reference, expect_violation
) -> None:
    asset_id = make_reference(project_id=project_id, character_id=character_id)
    assert api_client.post(f"/api/reference-assets/{asset_id}/approve").status_code == 200

    expect_violation(
        "UPDATE reference_assets SET storage_key = 'blobs/zz/other.png' WHERE id = :id",
        {"id": asset_id},
        match="immutable",
    )


def test_review_unknown_reference_returns_404(api_client) -> None:
    missing = api_client.post(f"/api/reference-assets/{uuid.uuid4()}/approve")
    assert missing.status_code == 404
    assert api_client.post(f"/api/reference-assets/{uuid.uuid4()}/reject").status_code == 404
