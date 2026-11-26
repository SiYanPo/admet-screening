@echo off
chcp 65001 >nul
title ADMET 一键推送
cd /d "C://Users//huawei//.workbuddy//skills//admet-screening"
echo.
echo  ============================================
echo   ADMET 投稿包 - 一键建仓库并推送
echo  ============================================
echo.
echo  需要: 一个带 repo 权限的 GitHub token
echo  获取: https://github.com/settings/tokens/new
echo        Note 填 admet-deposit，底部勾 repo，点 Generate
echo.
set /p TOKEN=请粘贴 token 后回车: 
if "%TOKEN%"=="" goto NOTOKEN
echo.
python tools\finish_push.py --token %TOKEN%
echo.
goto END
:NOTOKEN
echo 未输入 token，已退出。
:END
pause
