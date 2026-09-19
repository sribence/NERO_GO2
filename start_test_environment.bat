@echo off
REM NERO GO2 -- offline teszt-kornyezet inditasa (robot nelkul).
REM 3 kulon ablak: mock Hesai bridge, KISS-ICP live mod, YOLO teszt.

set ROOT=%~dp0

echo [1/3] Mock Hesai bridge inditasa (:5003)...
start "MOCK-HESAI-BRIDGE" cmd /k python "%ROOT%docker\hesai_bridge\mock_hesai_bridge.py"

timeout /t 2 /nobreak >nul

echo [2/3] KISS-ICP live mod inditasa (bridge: localhost:5003)...
start "KISS-ICP-LIVE" cmd /k python "%ROOT%docker\mapping\run_kiss_icp.py" --live http://localhost:5003

echo [3/3] YOLO detektor teszt (ultralytics bus.jpg minta kepen)...
start "YOLO-TEST" cmd /k python "%ROOT%docker\realsense_bridge\yolo_detector.py" https://ultralytics.com/images/bus.jpg

echo.
echo Mind a 3 folyamat kulon ablakban fut. Zarasukhoz csukd be az ablakokat.
