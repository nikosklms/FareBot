# Global Region Airport Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add primary major gateway hub airports across Asia, North America, Latin America, Africa, and Middle East in `services/airports_data.py`.

**Architecture:** Update `GLOBAL_REGIONS_AIRPORTS` dictionary in `services/airports_data.py` with validated airport IATA codes, names, and country labels.

**Tech Stack:** Python 3.13, pytest

## Global Constraints
- Preserve existing airport entries and structure.
- Ensure all IATA codes are uppercase and unique within their region list.

---

### Task 1: Update `GLOBAL_REGIONS_AIRPORTS` in `services/airports_data.py`

**Files:**
- Modify: `services/airports_data.py`
- Test: `tests/test_airports_data.py`

- [ ] **Step 1: Write tests in `tests/test_airports_data.py` verifying new primary hub additions**

```python
def test_new_airport_hubs_exist():
    from services.airports_data import get_region_airports
    
    asia_codes = [a["code"] for a in get_region_airports("asia")]
    assert "NRT" in asia_codes
    assert "TPE" in asia_codes
    
    na_codes = [a["code"] for a in get_region_airports("north_america")]
    assert "EWR" in na_codes
    assert "SEA" in na_codes

    latam_codes = [a["code"] for a in get_region_airports("latin_america")]
    assert "GIG" in latam_codes
    assert "MDE" in latam_codes

    africa_codes = [a["code"] for a in get_region_airports("africa")]
    assert "ZNZ" in africa_codes
    assert "SEZ" in africa_codes

    me_codes = [a["code"] for a in get_region_airports("middle_east")]
    assert "IST" in me_codes
    assert "BEY" in me_codes
```

- [ ] **Step 2: Run pytest to verify failure**

Run: `./venv/bin/pytest tests/test_airports_data.py`
Expected: FAIL

- [ ] **Step 3: Update `GLOBAL_REGIONS_AIRPORTS` in `services/airports_data.py`**

Add the proposed primary hub airports to `asia`, `north_america`, `latin_america`, `africa`, and `middle_east`.

- [ ] **Step 4: Run pytest to verify all tests pass**

Run: `./venv/bin/pytest`
Expected: PASS (116 passed)

- [ ] **Step 5: Commit changes**

```bash
git add services/airports_data.py tests/test_airports_data.py
git commit -m "feat: expand major hub airports across global regions"
```
