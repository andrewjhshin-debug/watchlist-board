@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PATH=%PATH%;C:\Program Files\GitHub CLI
set REPO=watchlist-board

gh auth status >nul 2>&1 || (
  echo [1/4] GitHub 로그인 - 브라우저가 열리면 화면의 코드를 입력하고 승인하세요.
  gh auth login --web --git-protocol https -h github.com || goto :fail
)
for /f %%u in ('gh api user -q .login') do set GHUSER=%%u

echo [2/4] 저장소 만들고 올리는 중...
if not exist .git (
  git init -q -b main
  git config user.name %GHUSER%
  git config user.email %GHUSER%@users.noreply.github.com
)
git add -A && git commit -q -m "관심종목 보드" 2>nul
gh repo view %GHUSER%/%REPO% >nul 2>&1 || gh repo create %REPO% --public --source . --remote origin || goto :fail
git push -q -u origin main || goto :fail
gh api -X POST repos/%GHUSER%/%REPO%/pages -f build_type=workflow >nul 2>&1

echo [3/4] 텔레그램 알림 키 등록 (출자공고 알림 봇 그대로 사용)...
python -c "import json;print(json.load(open('../lp-notice-monitor/config/notify.json',encoding='utf-8'))['telegram']['bot_token'])" | gh secret set TG_TOKEN || goto :fail
python -c "import json;print(json.load(open('../lp-notice-monitor/config/notify.json',encoding='utf-8'))['telegram']['chat_id'])" | gh secret set TG_CHAT_ID || goto :fail

echo [4/4] 첫 갱신 실행...
gh workflow run update.yml
echo.
echo 완료! 1~2분 뒤 폰에서 이 주소를 여세요 (홈 화면에 추가 추천):
echo    https://%GHUSER%.github.io/%REPO%/
echo.
echo 종목/목표가를 바꾼 뒤에는 이 파일을 다시 더블클릭하면 반영됩니다.
pause
exit /b

:fail
echo.
echo 중간에 실패했습니다. 이 창 내용을 캡처해서 Claude 에게 보여주세요.
pause
