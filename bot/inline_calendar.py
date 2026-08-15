import calendar
from datetime import datetime, timezone
from typing import Tuple, Optional
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def create_calendar(year: int, month: int, mode: str = "single", start_date: Optional[str] = None) -> InlineKeyboardMarkup:
    """Create an interactive Telegram inline keyboard calendar."""
    keyboard = []
    
    # Calculate prev/next month
    if month == 1:
        prev_year, prev_month = year - 1, 12
    else:
        prev_year, prev_month = year, month - 1
        
    if month == 12:
        next_year, next_month = year + 1, 1
    else:
        next_year, next_month = year, month + 1

    month_name = calendar.month_name[month]
    
    # Header Row: Prev Month | Month Year | Next Month
    header_row = [
        InlineKeyboardButton("«", callback_data=f"cal_nav_{prev_year:04d}-{prev_month:02d}"),
        InlineKeyboardButton(f"{month_name[:3]} {year}", callback_data="cal_ignore"),
        InlineKeyboardButton("»", callback_data=f"cal_nav_{next_year:04d}-{next_month:02d}")
    ]
    keyboard.append(header_row)
    
    # Days of week header
    week_days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    keyboard.append([InlineKeyboardButton(day, callback_data="cal_ignore") for day in week_days])
    
    # Month grid
    month_days = calendar.monthcalendar(year, month)
    today = datetime.now(timezone.utc).date()
    start_date_obj = datetime.strptime(start_date, "%Y-%m-%d").date() if (start_date and isinstance(start_date, str)) else None
    
    for week in month_days:
        row = []
        for day in week:
            if day == 0:
                row.append(InlineKeyboardButton(" ", callback_data="cal_ignore"))
            else:
                date_str = f"{year:04d}-{month:02d}-{day:02d}"
                day_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                
                min_date = start_date_obj if (start_date_obj and start_date_obj > today) else today
                
                if day_date < min_date:
                    row.append(InlineKeyboardButton("·", callback_data="cal_ignore"))
                elif start_date_obj and day_date == start_date_obj:
                    row.append(InlineKeyboardButton(f"🚩{day}", callback_data=f"cal_day_{date_str}"))
                else:
                    row.append(InlineKeyboardButton(str(day), callback_data=f"cal_day_{date_str}"))
        keyboard.append(row)
        
    # Footer Row: Mode toggle and Cancel
    mode_btn = InlineKeyboardButton(
        "📅 Range Mode" if mode == "single" else "📅 Single Mode",
        callback_data="cal_mode_range" if mode == "single" else "cal_mode_single"
    )
    cancel_btn = InlineKeyboardButton("❌ Cancel", callback_data="cal_cancel")
    keyboard.append([mode_btn, cancel_btn])
    
    return InlineKeyboardMarkup(keyboard)

def parse_calendar_callback(callback_data: str) -> Tuple[str, str]:
    """Parse callback_data from calendar inline buttons."""
    if callback_data.startswith("cal_day_"):
        return ("DAY", callback_data.replace("cal_day_", ""))
    elif callback_data.startswith("cal_nav_"):
        return ("NAV", callback_data.replace("cal_nav_", ""))
    elif callback_data.startswith("cal_mode_"):
        return ("MODE", callback_data.replace("cal_mode_", ""))
    elif callback_data == "cal_cancel":
        return ("CANCEL", "cancel")
    return ("IGNORE", "")
