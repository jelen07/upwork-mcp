"""Tests for MCP tools."""

import pytest
from pydantic import ValidationError


def test_job_search_params_validation():
    """Test JobSearchParams validation."""
    from upwork_mcp.tools.jobs import JobSearchParams

    # Valid params
    params = JobSearchParams(query="python developer")
    assert params.query == "python developer"
    assert params.limit == 20

    # With optional params
    params = JobSearchParams(
        query="python",
        budget_min=100,
        experience_level="expert",
        limit=10,
    )
    assert params.budget_min == 100
    assert params.experience_level == "expert"
    assert params.limit == 10

    # Invalid limit
    with pytest.raises(ValidationError):
        JobSearchParams(query="test", limit=100)


def test_job_details_params_validation():
    """Test JobDetailsParams validation."""
    from upwork_mcp.tools.jobs import JobDetailsParams

    # Valid URL
    params = JobDetailsParams(job_url="https://www.upwork.com/jobs/~01234567890")
    assert "upwork.com" in params.job_url

    # Job ID only
    params = JobDetailsParams(job_url="~01234567890")
    assert params.job_url == "~01234567890"


def test_proposals_params_validation():
    """Test ProposalsParams validation."""
    from upwork_mcp.tools.proposals import ProposalsParams

    params = ProposalsParams()
    assert params.status == "active"
    assert params.limit == 20

    params = ProposalsParams(status="archived", limit=10)
    assert params.status == "archived"


def test_messages_params_validation():
    """Test MessagesParams validation."""
    from upwork_mcp.tools.messages import MessagesParams

    params = MessagesParams()
    assert params.unread_only is False
    assert params.limit == 20

    params = MessagesParams(unread_only=True)
    assert params.unread_only is True


def test_contracts_params_validation():
    """Test ContractsParams validation."""
    from upwork_mcp.tools.contracts import ContractsParams

    params = ContractsParams()
    assert params.status == "active"

    params = ContractsParams(status="ended")
    assert params.status == "ended"


def test_build_search_url_uses_real_endpoint():
    """Search must hit /nx/search/jobs/ with q=, not the personalised feed."""
    from upwork_mcp.tools.jobs import JobSearchParams, _build_search_url

    url = _build_search_url(JobSearchParams(query="python developer"))
    assert url.startswith("https://www.upwork.com/nx/search/jobs/?")
    assert "q=python+developer" in url


def test_build_search_url_encodes_filters():
    from upwork_mcp.tools.jobs import JobSearchParams, _build_search_url

    url = _build_search_url(
        JobSearchParams(
            query="rust",
            experience_level="expert",
            job_type="hourly",
            budget_min=1000,
            budget_max=5000,
            hourly_rate_min=80,
            payment_verified=True,
        )
    )
    assert "contractor_tier=3" in url
    assert "t=0" in url
    assert "amount=1000-5000" in url
    assert "hourly_rate=80-" in url
    assert "payment_verified_only=1" in url


def test_looks_like_settings_page():
    from upwork_mcp.tools.profile import _looks_like_settings_page

    assert _looks_like_settings_page("Settings", None) is True
    assert _looks_like_settings_page("settings", None) is True
    assert _looks_like_settings_page(None, "Profile") is True
    assert _looks_like_settings_page("Jane Doe", "Senior Backend Engineer") is False
    assert _looks_like_settings_page(None, None) is False


def test_extract_profile_from_next_data_basic():
    from upwork_mcp.tools.profile import _extract_profile_from_next_data

    payload = {
        "props": {
            "pageProps": {
                "freelancer": {
                    "firstName": "Jane",
                    "lastName": "Doe",
                    "title": "Senior Backend Engineer",
                    "description": "Go and Python distributed systems.",
                    "hourlyRate": {"amount": 95, "currency": "USD"},
                    "skills": [
                        "Go",
                        {"name": "Python"},
                        {"preferredLabel": "PostgreSQL"},
                    ],
                    "jobSuccessScore": 100,
                }
            }
        }
    }
    extracted = _extract_profile_from_next_data(payload)
    assert extracted["name"] == "Jane Doe"
    assert extracted["title"] == "Senior Backend Engineer"
    assert extracted["overview"].startswith("Go and Python")
    assert extracted["hourly_rate"] == "95 USD"
    assert extracted["skills"] == ["Go", "Python", "PostgreSQL"]
    assert extracted["job_success_score"] == "100%"


def test_extract_profile_from_next_data_handles_missing_keys():
    from upwork_mcp.tools.profile import _extract_profile_from_next_data

    assert _extract_profile_from_next_data({}) == {}
    assert _extract_profile_from_next_data({"props": {"pageProps": {}}}) == {}
