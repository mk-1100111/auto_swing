# Swing UIA Inspector

Windows 전용 Swing UIA 컨트롤 조사기입니다. `pywinauto` + Tkinter를 사용해 Auto ID, Name, Value, 좌표를 확인하고 선택 항목의 자동화 코드를 복사할 수 있습니다.

## 실행파일 설치 (Python 불필요)

1. [Releases / Latest](https://github.com/mk-1100111/auto_swing/releases/latest)에서 `SwingInspector-Portable.zip`을 다운로드합니다.
2. ZIP을 압축 해제하고 **`SwingLauncher.exe`** 를 실행합니다. `SwingInspector.exe`를 직접 실행하면 자동 업데이트 확인을 건너뜁니다.
3. 실행할 때마다 GitHub 최신 Release의 `update_manifest.json`과 로컬 프로그램의 SHA256을 비교합니다.
4. 새 버전이 있으면 파일을 임시 경로로 다운로드하여 SHA256과 크기 검증 뒤 원자적으로 교체하고 프로그램을 실행합니다.
5. 다운로드/교체 실패 시 오류 팝업과 로그를 남기고 **다시 시도 / 기존 버전 실행 / 중단** 중 선택할 수 있습니다. 자동으로 예전 버전을 최신인 것처럼 실행하지 않습니다.

> **중요:** `SwingLauncher.exe`와 `SwingInspector.exe`를 같은 폴더에 보관하세요. 자동 업데이트는 **앱 본체**를 교체하며 런처 자체는 교체하지 않습니다. **구형 런처(build-1, build-2)** 는 실패 메시지가 화면에 나타나지 않는 문제가 있어, 최신 Portable ZIP을 **한 번 새로 받아 두 EXE를 함께 교체**해야 합니다. 프로그램 창을 완전히 종료하고 압축을 해제하세요.

### 앱 기능

- 새로고침(F5): 현재 열린 `Swing` 창의 화면 컨트롤을 백그라운드에서 읽기
- 검색: Auto ID, 텍스트, 값, 컨트롤 종류, 좌표로 필터
- 컨트롤 선택: Auto ID, Name, Value, Window Text, 좌표 등 상세 확인
- 좌표(LTRB) 열 더블클릭: 선택 컨트롤 영역의 **중앙 좌표**로 마우스 포인터 이동 (클릭하지 않음)
- 선택 항목의 ID, 텍스트, 값, 좌표 및 Python 찾기/클릭/입력 코드 복사
- 좌표로 이동 버튼과 마우스 우클릭 메뉴에서도 좌표 이동 지원. TXT 로그처럼 좌표가 없는 항목은 이동하지 않음
- TXT 로그 불러오기 / CSV 내보내기
- 메모장: `%LOCALAPPDATA%\Swing_UIA_Inspector\notes.txt`에 자동 저장 (업데이트와 무관)

### 소스 코드 실행

```powershell
py -3 -m pip install -r requirements.txt
py -3 swing_inspector.py
```

### 소스 런처 테스트 (Windows)

```powershell
py -3 updater.py
```

## 배포 자동화

`main` 브랜치에 푸시하면 `.github/workflows/windows-release.yml`이 Windows 환경에서 단위 테스트를 수행한 뒤 PyInstaller로 2개 EXE를 생성하고 새 GitHub Release를 `latest`로 게시합니다.

- `SwingLauncher.exe` : 업데이트 체크 후 앱 실행, 변하지 않는 시작 진입점
- `SwingInspector.exe` : GUI 앱 본체 (자동 교체됨)
- `update_manifest.json` : 원격 파일 SHA256 / 바이트 수
- `SwingInspector-Portable.zip` : 최초 다운로드용 포터블 배포판

본 앱은 Swing 화면의 UIA를 조회하며, 사용자가 좌표 열을 더블클릭할 때만 마우스 커서를 이동합니다. **실제 클릭은 하지 않습니다.** 화면 레이아웃이 바뀌었다면 새로고침(F5)으로 좌표를 갱신하세요. 복사한 Python 코드 중 `click_input()`/`set_edit_text()`는 실행자가 직접 사용한 경우에만 Swing 화면에 영향을 줍니다.

## 보안 및 제한

- 업데이터는 지정된 공개 GitHub 저장소 Release에만 접속하고, 다운로드 파일의 SHA256과 크기를 검증합니다. 임시 다운로드나 검사 실패 시 기존 EXE를 유지합니다.
- 고객명/연락처 등 업무 데이터가 포함된 CSV나 메모는 사용자의 컴퓨터에만 보관하며, GitHub로 자동 업로드하지 않습니다.
- 앱 본체가 실행 중이라 파일 교체가 거부되면 창을 종료한 후 팝업에서 **다시 시도**를 눌러 검증된 업데이트 파일로 교체합니다.
- 네트워크/권한 오류가 발생한 경우 메시지로 이유를 보여주고 **다시 시도 / 기존 버전 실행 / 중단**을 명확하게 선택하게 합니다.
- 런처 진단 로그: `%LOCALAPPDATA%\Swing_UIA_Inspector\launcher.log` (사용자 PC에만 보관).
- 새 릴리스 게시 후 GitHub Actions가 성공해야 새로운 EXE가 배포됩니다.
- Windows에서 실제 Swing 프로그램을 이용한 UIA 검사는 별도로 확인해야 합니다.
