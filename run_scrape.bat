@echo off
cd /d "%~dp0"

echo === Getting latest leads from GitHub ===
git pull origin main --rebase --autostash
if errorlevel 1 (
  echo Pull failed. Fix the error above, then run this again.
  pause
  exit /b 1
)

echo.
echo === Running scraper ===
python scrape_clinics.py

echo.
echo === Saving results to GitHub ===
git add clinics_master.csv
if exist crawl_log.csv git add crawl_log.csv
git diff --cached --quiet
if errorlevel 1 (
  git commit -m "Local scrape: update leads database [skip ci]"
  git pull origin main --rebase --autostash
  git push origin main
) else (
  echo No changes to save.
)

echo.
echo Done.
pause
