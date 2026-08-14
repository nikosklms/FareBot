# Configurable Departure Timeframe for `/explore` & `/digest` Design Specification

> **Status:** APPROVED  
> **Date:** 2026-08-15  

## Executive Summary
Currently, `/explore` and `/digest` scan for flight deal offers departing at a hardcoded +30 days offset from the execution day. This spec adds an interactive **Timeframe Selection Step** to both `/explore` and `/digest` wizards, allowing users to choose departure horizons (`7d / Next Weekend`, `14d`, `30d (Default)`, `60d`, `90d`, or custom days/date). It also updates `/help` and `/start` documentation so the default and configurable timeframe options are fully transparent.

---

## 1. Interaction & Wizard Flow Updates

### 1.1 `/explore` Wizard Flow
- **Step 1/5**: Origin Airport Selection (`[ ATH - Athens ]`, text input)
- **Step 2/5**: Destination Region Selection (`[ 🇪🇺 Europe ]`, `[ 🏝️ Greek Islands ]`, etc.)
- **Step 3/5 (NEW)**: Departure Timeframe Selection (`[ ⚡ Next Weekend (7d) ]`, `[ 🗓️ 30 Days (Default) ]`, `[ ✈️ 60 Days ]`, `[ 🌍 90 Days ]`, or type custom offset/date)
- **Step 4/5**: Target Budget Threshold (`[ €50 ]`, `[ €100 ]`, etc.)
- **Step 5/5**: Maximum Results Count Limit (`[ 5 ]`, `[ 10 (Default) ]`, `[ 15 ]`, `[ 20 ]`)

**Shortcut Syntax**: `/explore ATH europe 30 100 10`

### 1.2 `/digest` Wizard Flow
- **Step 1/7**: Origin Airport Selection
- **Step 2/7**: Destination Region Selection
- **Step 3/7**: Target Budget Threshold
- **Step 4/7 (NEW)**: Target Departure Timeframe (`[ 14 Days ]`, `[ 30 Days (Default) ]`, `[ 60 Days ]`, `[ 90 Days ]`)
- **Step 5/7**: Delivery Day of Week (`[ Sunday (Default) ]`, `[ Friday ]`, etc.)
- **Step 6/7**: Delivery Time of Day (`[ 09:00 ]`, `[ 15:00 (Default) ]`, etc.)
- **Step 7/7**: Maximum Deals Count Limit (`[ 5 ]`, `[ 10 (Default) ]`, etc.)

**Shortcut Syntax**: `/digest ATH europe 30 80 Sunday@15:00 10`

---

## 2. Database & Data Model

- In SQLite `trackers` table:
  - Digest rows store the target offset + schedule in `departure_date` or as structured timeframe token, e.g. `30d|Sunday@15:00`.
  - When the weekly job executes, `run_digest_weekly_job` computes `dep_date = datetime.now(timezone.utc) + timedelta(days=offset_days)`.

---

## 3. User Documentation (`bot/handlers/common.py`)

- Update `/help` and `/start` commands text:
  - Explicitly mention that deal discovery scans flights departing **30 days ahead by default**, and can be set to 7d, 14d, 30d, 60d, or 90d.
