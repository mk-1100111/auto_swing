# Swing UIA Inspector

Windows 전용 Swing UIA 컨트롤 조사기입니다. `pywinauto` + Tkinter를 사용해 Auto ID, Name, Value, 좌표를 확인하고 선택 항목의 자동화 코드를 복사할 수 있습니다.

## 실행파일 설치 (Python 불필요)

1. [Releases / Latest](https://github.com/mk-1100111/auto_swing/releases/latest)에서 `SwingInspector-Portable.zip`을 다운로드합니다.
2. ZIP을 압축 해제하고 **`SwingLauncher.exe`** 를 실행합니다. `SwingInspector.exe`를 직접 실행하면 자동 업데이트 확인을 건너뜁니다.
3. 실행할 때마다 GitHub 최신 Release의 `update_manifest.json`과 로컬 프로그램의 SHA256을 비교합니다.
4. 새 버전이 있으면 파일을 임시 경로로 다운로드하여 SHA256과 크기 검증 뒤 원자적으로 교체하고 프로그램을 실행합니다.
5. 인터넷이 없거나 업데이트에 실패하면 설치된 `SwingInspector.exe`를 계속 실행합니다.

> **중요:** `SwingLauncher.exe`와 `SwingInspector.exe`를 같은 폴더에 보관하세요. 자동 업데이트는 **앱 본체**를 교체하며 런처 자체는 교체하지 않습니다. 런처 기능이 변경되면 새 Portable ZIP으로 교체하세요. 최초 설치 후 인터넷이 없다면 함께 압축 해제된 앱 본체로 실행됩니다.

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
- 실행 중인 EXE가 다른 프로세스에서 사용되어 교체 불가능하면 기존 버전을 실행합니다.
- 새 릴리스 게시 후 GitHub Actions가 성공해야 새로운 EXE가 배포됩니다.
- Windows에서 실제 Swing 프로그램을 이용한 UIA 검사는 별도로 확인해야 합니다.
