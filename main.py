# Copyright (c) 2026 (주)아이티언. All rights reserved.
# Author: jhpark@itian.co.kr

import os
import sys
import csv
import io
import threading
from concurrent.futures import ThreadPoolExecutor
import requests
import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image


# ── Resource helper ───────────────────────────────────────────────────────────

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)


# ── SCIM API ──────────────────────────────────────────────────────────────────

def get_all_scim_users(tenant_name, token, log_callback=None):
    url = f"https://{tenant_name}.goskope.com/api/v2/scim/Users"
    headers = {
        "accept": "application/scim+json;charset=utf-8",
        "Authorization": f"Bearer {token}",
    }

    def log(msg):
        if log_callback:
            log_callback(msg)

    all_users = []
    start_index = 1
    count = 100

    while True:
        try:
            response = requests.get(
                url, headers=headers,
                params={"startIndex": start_index, "count": count},
                timeout=30
            )
            if response.status_code != 200:
                log(f"사용자 목록 조회 실패 [{response.status_code}] {response.text}")
                return None

            data = response.json()
            resources = data.get("Resources", [])
            total = data.get("totalResults", 0)
            all_users.extend(resources)

            if len(all_users) >= total or not resources:
                break
            start_index += count

        except Exception as e:
            log(f"요청 에러: {e}")
            return None

    return all_users


def create_single_user(tenant_name, token, email, family_name, given_name):
    url = f"https://{tenant_name}.goskope.com/api/v2/scim/Users"
    headers = {
        "accept": "application/scim+json;charset=utf-8",
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {
        "active": True,
        "emails": [{"primary": True, "value": email}],
        "externalId": f"User-Ext_{email}",
        "meta": {"resourceType": "User"},
        "name": {"familyName": family_name, "givenName": given_name},
        "schemas": [
            "urn:ietf:params:scim:schemas:core:2.0:User",
            "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User",
            "urn:ietf:params:scim:schemas:extension:tenant:2.0:User"
        ],
        "userName": email
    }
    return requests.post(url, json=payload, headers=headers, timeout=30)


def create_users_from_csv(tenant_name, token, csv_path, log_callback=None, done_callback=None):
    url = f"https://{tenant_name}.goskope.com/api/v2/scim/Users"
    headers = {
        "accept": "application/scim+json;charset=utf-8",
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    def log(msg):
        if log_callback:
            log_callback(msg)

    result = {"success": 0, "fail": 0, "skip": 0}

    try:
        if not os.path.exists(csv_path):
            log(f"오류: '{csv_path}' 파일이 존재하지 않습니다.")
            if done_callback:
                done_callback(result)
            return

        with open(csv_path, mode="r", encoding="utf-8-sig") as file:
            reader = csv.DictReader(file)

            if not reader.fieldnames:
                log("오류: CSV 파일 헤더를 읽을 수 없습니다.")
                if done_callback:
                    done_callback(result)
                return

            fieldnames = [f.strip() for f in reader.fieldnames]
            required = {"email", "familyName", "givenName"}

            if not required.issubset(fieldnames):
                log("오류: 헤더에 email, familyName, givenName 이 필요합니다.")
                log(f"현재 헤더: {fieldnames}")
                if done_callback:
                    done_callback(result)
                return

            log("CSV 일괄 생성 시작...")
            log("")

            for row_num, row in enumerate(reader, start=2):
                row = {k.strip(): v for k, v in row.items() if k is not None}
                email = (row.get("email") or "").strip()
                family = (row.get("familyName") or "").strip()
                given = (row.get("givenName") or "").strip()

                if not email or not family or not given:
                    log(f"건너뜀 (Row {row_num}): 필수 데이터 누락")
                    result["skip"] += 1
                    continue

                payload = {
                    "active": True,
                    "emails": [{"primary": True, "value": email}],
                    "externalId": f"User-Ext_{email}",
                    "meta": {"resourceType": "User"},
                    "name": {"familyName": family, "givenName": given},
                    "schemas": [
                        "urn:ietf:params:scim:schemas:core:2.0:User",
                        "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User",
                        "urn:ietf:params:scim:schemas:extension:tenant:2.0:User"
                    ],
                    "userName": email
                }

                try:
                    resp = requests.post(url, json=payload, headers=headers, timeout=30)
                    if resp.status_code in (200, 201):
                        log(f"성공 [{resp.status_code}] -> {email}")
                        result["success"] += 1
                    else:
                        log(f"실패 [{resp.status_code}] {email} / {resp.text}")
                        result["fail"] += 1
                except Exception as e:
                    log(f"요청 에러 ({email}): {e}")
                    result["fail"] += 1

            log("")
            log(f"=== CSV 완료: 성공 {result['success']} / 실패 {result['fail']} / 건너뜀 {result['skip']} ===")

    finally:
        if done_callback:
            done_callback(result)


def delete_scim_users(tenant_name, token, users, log_callback=None, done_callback=None):
    url_base = f"https://{tenant_name}.goskope.com/api/v2/scim/Users"
    headers = {
        "accept": "application/scim+json;charset=utf-8",
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    result = {"success": 0, "fail": 0}

    def log(msg):
        if log_callback:
            log_callback(msg)

    try:
        log(f"{len(users)}명의 사용자를 삭제합니다...")
        log("")

        for user in users:
            user_id = user.get("id")
            user_name = user.get("userName", "unknown")

            if not user_id:
                log(f"건너뜀: ID 없음 ({user_name})")
                result["fail"] += 1
                continue

            try:
                resp = requests.delete(f"{url_base}/{user_id}", headers=headers, timeout=30)
                if resp.status_code in (200, 204):
                    log(f"삭제 성공 [{resp.status_code}] -> {user_name}")
                    result["success"] += 1
                else:
                    log(f"삭제 실패 [{resp.status_code}] {user_name} / {resp.text}")
                    result["fail"] += 1
            except Exception as e:
                log(f"요청 에러 ({user_name}): {e}")
                result["fail"] += 1

        log("")
        log(f"=== 삭제 완료: 성공 {result['success']} / 실패 {result['fail']} ===")

    finally:
        if done_callback:
            done_callback(result)


# ── SCIM Group API ────────────────────────────────────────────────────────────

def _scim_headers(token):
    return {
        "accept": "application/scim+json;charset=utf-8",
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }


def get_all_scim_groups(tenant_name, token, log_callback=None):
    url = f"https://{tenant_name}.goskope.com/api/v2/scim/Groups"
    headers = _scim_headers(token)

    def log(msg):
        if log_callback:
            log_callback(msg)

    all_groups = []
    start_index = 1
    count = 100

    while True:
        try:
            response = requests.get(
                url, headers=headers,
                params={"startIndex": start_index, "count": count},
                timeout=30
            )
            if response.status_code != 200:
                log(f"그룹 목록 조회 실패 [{response.status_code}] {response.text}")
                return None

            data = response.json()
            resources = data.get("Resources", [])
            total = data.get("totalResults", 0)
            all_groups.extend(resources)

            if len(all_groups) >= total or not resources:
                break
            start_index += count

        except Exception as e:
            log(f"요청 에러: {e}")
            return None

    return all_groups


def get_scim_group(tenant_name, token, group_id):
    url = f"https://{tenant_name}.goskope.com/api/v2/scim/Groups/{group_id}"
    return requests.get(
        url, headers=_scim_headers(token),
        params={"attributes": "members"},   # Netskope는 명시해야 members를 돌려줌
        timeout=30
    )


def create_scim_group(tenant_name, token, display_name, member_ids=None):
    url = f"https://{tenant_name}.goskope.com/api/v2/scim/Groups"
    payload = {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:Group"],
        "displayName": display_name,
        "externalId": f"Group-Ext_{display_name}",
        "meta": {"resourceType": "Group"},
        "members": [{"value": uid} for uid in (member_ids or [])]
    }
    return requests.post(url, json=payload, headers=_scim_headers(token), timeout=30)


def patch_group_members(tenant_name, token, group_id, op, user_ids):
    """op: "add" | "remove" """
    url = f"https://{tenant_name}.goskope.com/api/v2/scim/Groups/{group_id}"
    if op == "add":
        operations = [{
            "op": "add", "path": "members",
            "value": [{"value": uid} for uid in user_ids]
        }]
    else:
        operations = [
            {"op": "remove", "path": f'members[value eq "{uid}"]'}
            for uid in user_ids
        ]
    payload = {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
        "Operations": operations
    }
    return requests.patch(url, json=payload, headers=_scim_headers(token), timeout=30)


def delete_scim_group(tenant_name, token, group_id):
    url = f"https://{tenant_name}.goskope.com/api/v2/scim/Groups/{group_id}"
    return requests.delete(url, headers=_scim_headers(token), timeout=30)


# ── Design tokens ─────────────────────────────────────────────────────────────

C = {
    "bg":        "#070B14",
    "card":      "#0F172A",
    "card2":     "#111827",
    "row_odd":   "#0D1526",
    "row_even":  "#0A1020",
    "border":    "#1F2A44",
    "text":      "#E5E7EB",
    "sub":       "#94A3B8",
    "accent":    "#3B82F6",
    "accent2":   "#2563EB",
}

COPYRIGHT = "© 2026 (주)아이티언. All rights reserved.  ·  jhpark@itian.co.kr"


def copyright_label(parent):
    return ctk.CTkLabel(
        parent, text=COPYRIGHT,
        font=ctk.CTkFont(family="맑은 고딕", size=11),
        text_color="#64748B"
    )



# ── Login frame ───────────────────────────────────────────────────────────────

class LoginFrame(ctk.CTkFrame):
    def __init__(self, master, on_connect, logo_image=None):
        super().__init__(master, fg_color=C["bg"])
        self.on_connect = on_connect
        self.logo_image = logo_image
        self._build()

    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        card = ctk.CTkFrame(
            self, fg_color=C["card"], corner_radius=20,
            border_width=1, border_color=C["border"]
        )
        card.grid(row=0, column=0, padx=80, pady=(60, 12), sticky="nsew")
        card.grid_columnconfigure(0, weight=1)

        copyright_label(self).grid(row=1, column=0, pady=(0, 14))

        if self.logo_image:
            ctk.CTkLabel(card, text="", image=self.logo_image).grid(
                row=0, column=0, pady=(40, 12)
            )

        ctk.CTkLabel(
            card, text="SCIM 사용자 관리 툴",
            font=ctk.CTkFont(family="맑은 고딕", size=24, weight="bold"),
            text_color=C["text"]
        ).grid(row=1, column=0, pady=(0, 6))

        ctk.CTkLabel(
            card, text="Netskope 테넌트에 연결하세요",
            font=ctk.CTkFont(family="맑은 고딕", size=13),
            text_color=C["sub"]
        ).grid(row=2, column=0, pady=(0, 32))

        def entry(placeholder, row, show=None):
            e = ctk.CTkEntry(
                card, height=46, corner_radius=12,
                border_width=1, border_color=C["border"],
                fg_color="#0B1220", text_color=C["text"],
                placeholder_text=placeholder,
                font=ctk.CTkFont(family="맑은 고딕", size=13),
                show=show
            )
            e.grid(row=row, column=0, padx=44, pady=(0, 14), sticky="ew")
            return e

        self.tenant_entry = entry("테넌트 이름  (예: test.goskope.com 이면 test 입력)", 3)
        self.token_entry  = entry("API 토큰", 4, show="•")

        self.connect_btn = ctk.CTkButton(
            card, text="연결하기", height=50, corner_radius=14,
            fg_color=C["accent"], hover_color=C["accent2"],
            font=ctk.CTkFont(family="맑은 고딕", size=14, weight="bold"),
            command=self._connect
        )
        self.connect_btn.grid(row=5, column=0, padx=44, pady=(8, 10), sticky="ew")

        self.status_lbl = ctk.CTkLabel(
            card, text="",
            font=ctk.CTkFont(family="맑은 고딕", size=12),
            text_color="#F87171"
        )
        self.status_lbl.grid(row=6, column=0, pady=(0, 40))

        self.tenant_entry.bind("<Return>", lambda _: self.token_entry.focus())
        self.token_entry.bind("<Return>",  lambda _: self._connect())

    def _connect(self):
        tenant = self.tenant_entry.get().strip()
        token  = self.token_entry.get().strip()

        if not tenant:
            self.status_lbl.configure(text="테넌트 이름을 입력해주세요.")
            return
        if not token:
            self.status_lbl.configure(text="API 토큰을 입력해주세요.")
            return

        self.connect_btn.configure(state="disabled", text="연결 중...")
        self.status_lbl.configure(text="사용자 목록을 불러오는 중...", text_color=C["sub"])

        def worker():
            users = get_all_scim_users(tenant, token)
            self.after(0, self._done, tenant, token, users)

        threading.Thread(target=worker, daemon=True).start()

    def _done(self, tenant, token, users):
        self.connect_btn.configure(state="normal", text="연결하기")
        if users is None:
            self.status_lbl.configure(
                text="연결 실패 — 테넌트 이름 또는 토큰을 확인하세요.",
                text_color="#F87171"
            )
        else:
            self.status_lbl.configure(text="")
            self.on_connect(tenant, token, users)


# ── Add-user dialog ───────────────────────────────────────────────────────────

class AddUserDialog(ctk.CTkToplevel):
    def __init__(self, master, tenant_name, token, on_success, log_cb):
        super().__init__(master)
        self.tenant_name = tenant_name
        self.token       = token
        self.on_success  = on_success
        self.log_cb      = log_cb

        self.title("사용자 추가")
        self.geometry("440x380")
        self.resizable(False, False)
        self.configure(fg_color=C["card"])
        self.grab_set()
        self._build()

    def _build(self):
        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self, text="사용자 단일 추가",
            font=ctk.CTkFont(family="맑은 고딕", size=18, weight="bold"),
            text_color=C["text"]
        ).grid(row=0, column=0, sticky="w", padx=36, pady=(30, 20))

        def entry(placeholder, row):
            e = ctk.CTkEntry(
                self, height=44, corner_radius=12,
                border_width=1, border_color=C["border"],
                fg_color="#0B1220", text_color=C["text"],
                placeholder_text=placeholder,
                font=ctk.CTkFont(family="맑은 고딕", size=13)
            )
            e.grid(row=row, column=0, padx=36, sticky="ew", pady=(0, 12))
            return e

        self.email_ent  = entry("이메일  (userName)", 1)
        self.family_ent = entry("성  (familyName)",   2)
        self.given_ent  = entry("이름  (givenName)",  3)

        self.err_lbl = ctk.CTkLabel(
            self, text="",
            font=ctk.CTkFont(family="맑은 고딕", size=12),
            text_color="#F87171"
        )
        self.err_lbl.grid(row=4, column=0, sticky="w", padx=36)

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.grid(row=5, column=0, padx=36, sticky="ew", pady=(14, 30))
        btn_row.grid_columnconfigure((0, 1), weight=1)

        ctk.CTkButton(
            btn_row, text="취소", height=44, corner_radius=12,
            fg_color="#334155", hover_color="#475569",
            font=ctk.CTkFont(family="맑은 고딕", size=13, weight="bold"),
            command=self.destroy
        ).grid(row=0, column=0, sticky="ew", padx=(0, 8))

        self.add_btn = ctk.CTkButton(
            btn_row, text="추가", height=44, corner_radius=12,
            fg_color=C["accent"], hover_color=C["accent2"],
            font=ctk.CTkFont(family="맑은 고딕", size=13, weight="bold"),
            command=self._submit
        )
        self.add_btn.grid(row=0, column=1, sticky="ew", padx=(8, 0))

    def _submit(self):
        email  = self.email_ent.get().strip()
        family = self.family_ent.get().strip()
        given  = self.given_ent.get().strip()

        if not email or not family or not given:
            self.err_lbl.configure(text="모든 항목을 입력해주세요.")
            return

        self.add_btn.configure(state="disabled", text="추가 중...")
        self.err_lbl.configure(text="")

        def worker():
            try:
                resp = create_single_user(self.tenant_name, self.token, email, family, given)
                self.after(0, self._result, resp, email)
            except Exception as e:
                self.after(0, self._error, str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _result(self, resp, email):
        if resp.status_code in (200, 201):
            self.log_cb(f"사용자 추가 성공 -> {email}")
            self.on_success()
            self.destroy()
        else:
            self.add_btn.configure(state="normal", text="추가")
            self.err_lbl.configure(text=f"실패 [{resp.status_code}]: {resp.text[:80]}")

    def _error(self, msg):
        self.add_btn.configure(state="normal", text="추가")
        self.err_lbl.configure(text=f"에러: {msg}")


# ── Sample CSV download dialog ────────────────────────────────────────────────

def save_sample_csv(master=None):
    path = filedialog.asksaveasfilename(
        title="예시 CSV 저장",
        defaultextension=".csv",
        initialfile="sample_users.csv",
        filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
    )
    if not path:
        return
    rows = [
        {"email": "hong.gildong@example.com", "familyName": "홍", "givenName": "길동"},
        {"email": "kim.minji@example.com",    "familyName": "김", "givenName": "민지"},
        {"email": "park.jiho@example.com",    "familyName": "박", "givenName": "지호"},
    ]
    try:
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=["email", "familyName", "givenName"])
            w.writeheader()
            w.writerows(rows)
        CustomDialog(master, "저장 완료", f"예시 CSV가 저장되었습니다.\n{path}", "info").show()
    except Exception as e:
        CustomDialog(master, "저장 오류", str(e), "error").show()


# ── Custom dialog ─────────────────────────────────────────────────────────────

class CustomDialog(ctk.CTkToplevel):
    _CFG = {
        "info":    {"icon": "ℹ",  "color": "#3B82F6", "hover": "#1D4ED8", "bg": "#0D2140", "border": "#1E3A6E"},
        "warning": {"icon": "⚠",  "color": "#F59E0B", "hover": "#D97706", "bg": "#261C00", "border": "#6B4800"},
        "error":   {"icon": "✕",  "color": "#EF4444", "hover": "#DC2626", "bg": "#280A0A", "border": "#7A1515"},
        "confirm": {"icon": "！", "color": "#F59E0B", "hover": "#D97706", "bg": "#261C00", "border": "#6B4800"},
    }

    def __init__(self, master, title, message, dialog_type="info", logo_image=None):
        super().__init__(master)
        self._result = False
        cfg = self._CFG.get(dialog_type, self._CFG["info"])
        self._color      = cfg["color"]
        self._hover      = cfg["hover"]
        self._icon_bg    = cfg["bg"]
        self._icon_bdr   = cfg["border"]
        self._icon_chr   = cfg["icon"]
        self._confirm    = (dialog_type == "confirm")
        self._logo_image = logo_image

        self.title("")
        self.resizable(False, False)
        self.configure(fg_color=C["card"])
        self.withdraw()   # 렌더 전에는 숨김

        self._build(title, message)
        self.after(20, self._show)

    def _build(self, title, message):
        self.grid_columnconfigure(0, weight=1)

        # ── 로고 ──
        if self._logo_image:
            ctk.CTkLabel(self, text="", image=self._logo_image).grid(
                row=0, column=0, pady=(24, 0)
            )

        # ── 아이콘 원 ──
        circle = ctk.CTkFrame(
            self, width=60, height=60, corner_radius=30,
            fg_color=self._icon_bg,
            border_width=2, border_color=self._icon_bdr
        )
        circle.grid(row=1, column=0, pady=(14, 14))
        circle.grid_propagate(False)
        circle.grid_columnconfigure(0, weight=1)
        circle.grid_rowconfigure(0, weight=1)
        ctk.CTkLabel(
            circle, text=self._icon_chr,
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color=self._color
        ).grid(row=0, column=0)

        # ── 제목 ──
        ctk.CTkLabel(
            self, text=title,
            font=ctk.CTkFont(family="맑은 고딕", size=16, weight="bold"),
            text_color=C["text"]
        ).grid(row=2, column=0, padx=40, pady=(0, 10))

        # ── 메시지 ──
        ctk.CTkLabel(
            self, text=message,
            font=ctk.CTkFont(family="맑은 고딕", size=13),
            text_color=C["sub"],
            wraplength=320,
            justify="center"
        ).grid(row=3, column=0, padx=40, pady=(0, 30))

        # ── 버튼 ──
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.grid(row=4, column=0, padx=36, sticky="ew", pady=(0, 32))

        if self._confirm:
            btn_row.grid_columnconfigure((0, 1), weight=1)
            ctk.CTkButton(
                btn_row, text="취소", height=44, corner_radius=12,
                fg_color="#1F2A44", hover_color="#2A3A5A",
                font=ctk.CTkFont(family="맑은 고딕", size=13, weight="bold"),
                text_color=C["sub"],
                command=self._cancel
            ).grid(row=0, column=0, sticky="ew", padx=(0, 8))
            ctk.CTkButton(
                btn_row, text="삭제", height=44, corner_radius=12,
                fg_color="#DC2626", hover_color="#B91C1C",
                font=ctk.CTkFont(family="맑은 고딕", size=13, weight="bold"),
                command=self._ok
            ).grid(row=0, column=1, sticky="ew", padx=(8, 0))
        else:
            btn_row.grid_columnconfigure(0, weight=1)
            ctk.CTkButton(
                btn_row, text="확인", height=44, corner_radius=12,
                fg_color=self._color, hover_color=self._hover,
                font=ctk.CTkFont(family="맑은 고딕", size=13, weight="bold"),
                command=self._ok
            ).grid(row=0, column=0, sticky="ew")

        self.bind("<Return>", lambda _: self._ok())
        self.bind("<Escape>", lambda _: self._cancel())

    def _show(self):
        self.update()    # 위젯 전체 렌더링 완료 대기
        w = 400
        h = self.winfo_reqheight()
        m = self.master
        if m:
            mx = m.winfo_rootx() + m.winfo_width()  // 2
            my = m.winfo_rooty() + m.winfo_height() // 2
        else:
            mx = self.winfo_screenwidth()  // 2
            my = self.winfo_screenheight() // 2
        self.geometry(f"{w}x{h}+{mx - w // 2}+{my - h // 2}")
        self.deiconify()   # 위치 잡은 뒤 표시
        self.grab_set()
        self.lift()
        self.focus_force()

    def _ok(self):
        self._result = True
        self.grab_release()
        self.destroy()

    def _cancel(self):
        self._result = False
        self.grab_release()
        self.destroy()

    def show(self):
        self.wait_window(self)

    def confirm(self):
        self.wait_window(self)
        return self._result


# ── Group manager dialog ──────────────────────────────────────────────────────

class GroupFrame(ctk.CTkFrame):
    def __init__(self, master, main_frame, log_cb, logo_image=None):
        super().__init__(master, fg_color="transparent")
        self.main_frame  = main_frame
        self.tenant_name = ""
        self.token       = ""
        self.log_cb      = log_cb
        self.logo_image  = logo_image
        self.groups         = []
        self.group_map      = {}     # treeview iid -> group dict
        self.group_tag      = {}     # treeview iid -> "odd"|"even"
        self.sel_group_iid  = None
        self.member_ids     = set()  # 선택된 그룹의 멤버 user id
        self.member_display = {}     # user id -> display (사용자 목록에 없는 멤버용)
        self.row_map        = {}     # treeview iid -> user id
        self.checked        = set()  # 체크된 user id
        self.busy = False
        self._build()

    def show(self, tenant_name, token):
        """화면 전환 시 호출 — 테넌트가 바뀌었으면 상태 초기화 후 최신 목록 조회"""
        if (tenant_name, token) != (self.tenant_name, self.token):
            self.tenant_name, self.token = tenant_name, token
            self.groups, self.group_map, self.group_tag = [], {}, {}
            self.sel_group_iid = None
            self.member_ids, self.member_display = set(), {}
            self.checked = set()
            self.group_tree.delete(*self.group_tree.get_children())
            self.member_lbl.configure(text="사용자 — 그룹을 선택하세요")
        self._render_users()
        self._load_groups()

    # ── layout ───────────────────────────────────────────────────

    def _build(self):
        self.grid_columnconfigure(0, weight=2)
        self.grid_columnconfigure(1, weight=5)
        self.grid_rowconfigure(0, weight=1)

        # ─ 왼쪽: 그룹 목록 ─
        left, _, lbar = self._card(0, "그룹 목록")
        self.new_btn      = self._btn(lbar, "+ 새 그룹", "#1D4ED8", "#1E40AF", self._create_group)
        self.gdel_btn     = self._btn(lbar, "그룹 삭제", "#991B1B", "#B91C1C", self._delete_group)
        self.grefresh_btn = self._btn(lbar, "새로고침",  "#1E3A5F", "#1D4ED8", self._load_groups)

        self.group_tree = self._tree(left, ("name", "count"))
        self.group_tree.heading("name",  text="그룹 이름")
        self.group_tree.heading("count", text="멤버")
        self.group_tree.column("name",  stretch=True,  minwidth=140, anchor="w")
        self.group_tree.column("count", stretch=False, width=60,     anchor="center")
        self.group_tree.bind("<Button-1>", self._on_group_click)

        # ─ 오른쪽: 사용자 목록 (멤버 여부 표시) ─
        right, self.member_lbl, rbar = self._card(1, "사용자 — 그룹을 선택하세요")
        self.madd_btn = self._btn(rbar, "선택 추가", "#0F766E", "#0D9488", self._add_members)
        self.mdel_btn = self._btn(rbar, "선택 제거", "#991B1B", "#B91C1C", self._remove_members)
        self.mcount_lbl = ctk.CTkLabel(
            rbar, text="",
            font=ctk.CTkFont(family="맑은 고딕", size=12),
            text_color=C["sub"]
        )
        self.mcount_lbl.pack(side="right")

        fbar = ctk.CTkFrame(right, fg_color="transparent")
        fbar.grid(row=2, column=0, columnspan=2, sticky="ew", padx=16, pady=(0, 10))
        fbar.grid_columnconfigure(0, weight=1)

        self.f_query = ctk.CTkEntry(
            fbar, height=34, corner_radius=10,
            border_width=1, border_color=C["border"],
            fg_color="#0B1220", text_color=C["text"],
            placeholder_text="🔍  이메일 또는 이름 검색",
            font=ctk.CTkFont(family="맑은 고딕", size=12),
        )
        self.f_query.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.f_query.bind("<KeyRelease>", self._render_users)

        self.f_member = ctk.CTkSegmentedButton(
            fbar,
            values=["전체", "멤버", "비멤버"],
            command=self._render_users,
            font=ctk.CTkFont(family="맑은 고딕", size=12),
            height=34,
            fg_color="#1F2A44",
            selected_color=C["accent"],
            selected_hover_color=C["accent2"],
            unselected_color="#1F2A44",
            unselected_hover_color="#2A3A5A",
            text_color=C["text"],
        )
        self.f_member.set("전체")
        self.f_member.grid(row=0, column=1)

        self.user_tree = self._tree(right, ("check", "email", "name", "member"))
        self.user_tree.heading("check",  text="☐", command=self._toggle_all_visible)
        self.user_tree.heading("email",  text="이메일 (userName)")
        self.user_tree.heading("name",   text="이름")
        self.user_tree.heading("member", text="소속")
        self.user_tree.column("check",  stretch=False, width=44,     anchor="center")
        self.user_tree.column("email",  stretch=True,  minwidth=200, anchor="w")
        self.user_tree.column("name",   stretch=False, width=130,    anchor="w")
        self.user_tree.column("member", stretch=False, width=90,     anchor="center")
        self.user_tree.tag_configure("member", background="#0B2A22", foreground="#6EE7B7")
        self.user_tree.bind("<Button-1>", self._on_user_click)

    def _card(self, col, title):
        card = ctk.CTkFrame(
            self, fg_color=C["card"], corner_radius=14,
            border_width=1, border_color=C["border"]
        )
        card.grid(row=0, column=col, sticky="nsew",
                  padx=(0, 6) if col == 0 else (6, 0), pady=(0, 10))
        card.grid_columnconfigure(0, weight=1)
        card.grid_rowconfigure(3, weight=1)

        lbl = ctk.CTkLabel(
            card, text=title,
            font=ctk.CTkFont(family="맑은 고딕", size=14, weight="bold"),
            text_color=C["text"]
        )
        lbl.grid(row=0, column=0, columnspan=2, sticky="w", padx=16, pady=(14, 8))

        bar = ctk.CTkFrame(card, fg_color="transparent")
        bar.grid(row=1, column=0, columnspan=2, sticky="ew", padx=16, pady=(0, 10))
        return card, lbl, bar

    def _btn(self, parent, text, fg, hover, cmd, width=100):
        btn = ctk.CTkButton(
            parent, text=text, width=width, height=34,
            corner_radius=10, fg_color=fg, hover_color=hover,
            font=ctk.CTkFont(family="맑은 고딕", size=12, weight="bold"),
            command=cmd
        )
        btn.pack(side="left", padx=(0, 8))
        return btn

    def _tree(self, card, columns):
        tree = ttk.Treeview(
            card, columns=columns, show="headings",
            style="Dark.Treeview", selectmode="none"
        )
        vsb = ttk.Scrollbar(
            card, orient="vertical", command=tree.yview,
            style="Dark.Vertical.TScrollbar"
        )
        tree.configure(yscrollcommand=vsb.set)
        tree.grid(row=3, column=0, sticky="nsew", padx=(16, 0), pady=(0, 16))
        vsb.grid(row=3, column=1, sticky="ns", padx=(2, 12), pady=(0, 16))

        tree.tag_configure("odd",  background=C["row_odd"],  foreground=C["text"])
        tree.tag_configure("even", background=C["row_even"], foreground=C["text"])
        tree.tag_configure("sel",  background="#1E3A5F",     foreground=C["text"])
        return tree

    # ── groups ───────────────────────────────────────────────────

    def _selected_group(self):
        return self.group_map.get(self.sel_group_iid)

    def _load_groups(self):
        if self.busy:
            return
        self._set_busy(True)

        def worker():
            groups = get_all_scim_groups(self.tenant_name, self.token, self.log_cb)
            if groups:
                # 목록 응답엔 members가 없어 그룹별 단건 조회로 멤버 수를 채움
                with ThreadPoolExecutor(max_workers=5) as pool:
                    for group, members in zip(groups, pool.map(self._fetch_members, groups)):
                        if members is not None:
                            group["members"] = members
            self.after(0, self._on_groups, groups)

        threading.Thread(target=worker, daemon=True).start()

    def _fetch_members(self, group):
        try:
            resp = get_scim_group(self.tenant_name, self.token, group["id"])
            if resp.status_code == 200:
                return resp.json().get("members", [])
            self.log_cb(f"멤버 수 조회 실패 [{resp.status_code}] {group.get('displayName', '?')}")
        except Exception as e:
            self.log_cb(f"요청 에러 ({group.get('displayName', '?')}): {e}")
        return None

    def _on_groups(self, groups):
        self._set_busy(False)
        if groups is None:
            self.log_cb("오류: 그룹 목록을 불러오지 못했습니다.")
            return

        prev_id = (self._selected_group() or {}).get("id")
        self.groups = groups
        self.group_tree.delete(*self.group_tree.get_children())
        self.group_map     = {}
        self.group_tag     = {}
        self.sel_group_iid = None

        reselect = None
        for idx, group in enumerate(sorted(groups, key=lambda g: g.get("displayName", "").lower())):
            tag     = "odd" if idx % 2 == 0 else "even"
            members = group.get("members")
            iid = self.group_tree.insert("", "end",
                values=(group.get("displayName", ""), len(members) if members is not None else "-"),
                tags=(tag,),
            )
            self.group_map[iid] = group
            self.group_tag[iid] = tag
            if group.get("id") == prev_id:
                reselect = iid

        self.log_cb(f"그룹 목록 조회 완료 — {len(groups)}개")
        if reselect:
            self._select_group(reselect)
        else:
            self.member_lbl.configure(text="사용자 — 그룹을 선택하세요")
            self.member_ids     = set()
            self.member_display = {}
            self._render_users()

    def _on_group_click(self, event):
        iid = self.group_tree.identify_row(event.y)
        if iid and iid != self.sel_group_iid and not self.busy:
            self._select_group(iid)

    def _select_group(self, iid):
        if self.sel_group_iid in self.group_tag:
            self.group_tree.item(self.sel_group_iid, tags=(self.group_tag[self.sel_group_iid],))
        self.group_tree.item(iid, tags=("sel",))
        self.sel_group_iid = iid
        self._load_members()

    def _create_group(self):
        if self.busy:
            return
        ids = list(self.checked)
        name = ctk.CTkInputDialog(
            title="새 그룹",
            text=f"그룹 이름을 입력하세요.\n\n오른쪽 목록에서 체크된 사용자 {len(ids)}명이\n멤버로 함께 추가됩니다."
        ).get_input()
        name = (name or "").strip()
        if not name:
            return
        if any(g.get("displayName") == name for g in self.groups):
            CustomDialog(self, "중복", f"'{name}' 그룹이 이미 존재합니다.", "warning",
                         logo_image=self.logo_image).show()
            return

        self._set_busy(True)

        def worker():
            ok = False
            try:
                resp = create_scim_group(self.tenant_name, self.token, name, ids)
                ok = resp.status_code in (200, 201)
                if ok:
                    self.log_cb(f"그룹 생성 성공 [{resp.status_code}] -> {name} (멤버 {len(ids)}명)")
                else:
                    self.log_cb(f"그룹 생성 실패 [{resp.status_code}] {name} / {resp.text}")
            except Exception as e:
                self.log_cb(f"요청 에러 ({name}): {e}")
            self.after(0, self._after_create, ok)

        threading.Thread(target=worker, daemon=True).start()

    def _after_create(self, ok):
        if ok:
            self.checked.clear()
        self._after_group_change()

    def _delete_group(self):
        if self.busy:
            return
        group = self._selected_group()
        if not group:
            CustomDialog(self, "선택 없음", "삭제할 그룹을 선택해주세요.", "warning",
                         logo_image=self.logo_image).show()
            return
        name = group.get("displayName", "?")
        if not CustomDialog(
            self, "그룹 삭제 확인",
            f"'{name}' 그룹을 삭제하시겠습니까?\n(사용자는 삭제되지 않습니다)\n\n이 작업은 되돌릴 수 없습니다.",
            "confirm", logo_image=self.logo_image
        ).confirm():
            return

        self._set_busy(True)

        def worker():
            try:
                resp = delete_scim_group(self.tenant_name, self.token, group["id"])
                if resp.status_code in (200, 204):
                    self.log_cb(f"그룹 삭제 성공 [{resp.status_code}] -> {name}")
                else:
                    self.log_cb(f"그룹 삭제 실패 [{resp.status_code}] {name} / {resp.text}")
            except Exception as e:
                self.log_cb(f"요청 에러 ({name}): {e}")
            self.after(0, self._after_group_change)

        threading.Thread(target=worker, daemon=True).start()

    def _after_group_change(self):
        self._set_busy(False)
        self._load_groups()

    # ── members ──────────────────────────────────────────────────

    def _load_members(self, pending=None):
        group = self._selected_group()
        if not group:
            return
        self.member_lbl.configure(text=f"사용자 — {group.get('displayName', '')}")
        self._set_busy(True)
        group_id = group["id"]

        def worker():
            members = None
            try:
                resp = get_scim_group(self.tenant_name, self.token, group_id)
                if resp.status_code == 200:
                    members = resp.json().get("members", [])
                else:
                    self.log_cb(f"그룹 조회 실패 [{resp.status_code}] {resp.text}")
            except Exception as e:
                self.log_cb(f"요청 에러: {e}")
            self.after(0, self._on_members, group_id, members, pending)

        threading.Thread(target=worker, daemon=True).start()

    def _on_members(self, group_id, members, pending=None):
        self._set_busy(False)
        if (self._selected_group() or {}).get("id") != group_id or members is None:
            return
        self.member_ids     = {m.get("value", "") for m in members}
        self.member_display = {m.get("value", ""): m.get("display", "") for m in members}
        self.group_tree.set(self.sel_group_iid, "count", len(self.member_ids))
        self._render_users()
        if pending:
            self._verify(*pending)

    def _verify(self, op, user_ids, name):
        """PATCH 후 재조회한 멤버 목록으로 실제 반영 여부 확인"""
        label   = "추가" if op == "add" else "제거"
        applied = [u for u in user_ids if (u in self.member_ids) == (op == "add")]
        missing = len(user_ids) - len(applied)
        self.log_cb(f"반영 확인: {name} — {len(applied)}/{len(user_ids)}명 {label} 확인됨")
        if missing:
            CustomDialog(self, "반영 확인 실패",
                         f"서버 재조회 결과 {len(user_ids)}명 중 {missing}명이 {label}되지 않았습니다.\n실행 로그를 확인해주세요.",
                         "warning", logo_image=self.logo_image).show()
        else:
            CustomDialog(self, "반영 완료",
                         f"'{name}' 그룹 멤버 {label} {len(applied)}명\n서버 재조회로 확인되었습니다.",
                         "info", logo_image=self.logo_image).show()

    def _render_users(self, *_):
        q    = self.f_query.get().strip().lower()
        mode = self.f_member.get()

        self.user_tree.delete(*self.user_tree.get_children())
        self.row_map = {}

        users = list(self.main_frame.users)
        known = {u.get("id") for u in users}
        users += [
            {"id": uid, "userName": self.member_display.get(uid) or uid}
            for uid in self.member_ids if uid not in known
        ]

        shown = 0
        for user in users:
            uid       = user.get("id", "")
            name_obj  = user.get("name", {})
            email     = user.get("userName", "")
            name      = f"{name_obj.get('familyName', '')}{name_obj.get('givenName', '')}"
            is_member = uid in self.member_ids

            if q and q not in email.lower() and q not in name.lower():
                continue
            if mode == "멤버"   and not is_member:
                continue
            if mode == "비멤버" and     is_member:
                continue

            tag = "member" if is_member else ("odd" if shown % 2 == 0 else "even")
            iid = self.user_tree.insert("", "end",
                values=(
                    "☑" if uid in self.checked else "☐",
                    email, name,
                    "✔ 멤버" if is_member else "—",
                ),
                tags=(tag,),
            )
            self.row_map[iid] = uid
            shown += 1

        visible = list(self.row_map.values())
        all_on  = bool(visible) and all(u in self.checked for u in visible)
        self.user_tree.heading("check", text="☑" if all_on else "☐")
        self.mcount_lbl.configure(
            text=f"멤버 {len(self.member_ids)}명 · 표시 {shown}명 · 체크 {len(self.checked)}명"
        )

    def _on_user_click(self, event):
        region = self.user_tree.identify_region(event.x, event.y)
        col    = self.user_tree.identify_column(event.x)
        iid    = self.user_tree.identify_row(event.y)
        if region != "cell" or col != "#1" or not iid:
            return
        uid = self.row_map[iid]
        if uid in self.checked:
            self.checked.discard(uid)
        else:
            self.checked.add(uid)
        self._render_users()

    def _toggle_all_visible(self):
        visible = list(self.row_map.values())
        if visible and all(u in self.checked for u in visible):
            self.checked.difference_update(visible)
        else:
            self.checked.update(visible)
        self._render_users()

    def _add_members(self):
        if self.busy:
            return
        group = self._selected_group()
        if not group:
            CustomDialog(self, "선택 없음", "그룹을 먼저 선택해주세요.", "warning",
                         logo_image=self.logo_image).show()
            return
        ids = [uid for uid in self.checked if uid not in self.member_ids]
        if not ids:
            CustomDialog(self, "선택 없음",
                         "추가할 사용자를 체크해주세요.\n(이미 멤버인 사용자는 제외됩니다)",
                         "warning", logo_image=self.logo_image).show()
            return
        self._patch_members(group, "add", ids)

    def _remove_members(self):
        if self.busy:
            return
        group = self._selected_group()
        ids   = [uid for uid in self.checked if uid in self.member_ids]
        if not group or not ids:
            CustomDialog(self, "선택 없음", "제거할 멤버를 체크해주세요.", "warning",
                         logo_image=self.logo_image).show()
            return
        if not CustomDialog(
            self, "멤버 제거 확인",
            f"'{group.get('displayName', '')}' 그룹에서 {len(ids)}명을 제거하시겠습니까?\n(사용자 계정은 삭제되지 않습니다)",
            "confirm", logo_image=self.logo_image
        ).confirm():
            return
        self._patch_members(group, "remove", ids)

    def _patch_members(self, group, op, user_ids):
        self._set_busy(True)
        label = "추가" if op == "add" else "제거"
        name  = group.get("displayName", "?")

        def worker():
            ok = False
            try:
                resp = patch_group_members(self.tenant_name, self.token, group["id"], op, user_ids)
                ok = resp.status_code in (200, 204)
                if ok:
                    self.log_cb(f"멤버 {label} 요청 성공 [{resp.status_code}] -> {name} ({len(user_ids)}명)")
                else:
                    self.log_cb(f"멤버 {label} 실패 [{resp.status_code}] {name} / {resp.text}")
            except Exception as e:
                self.log_cb(f"요청 에러 ({name}): {e}")
            self.after(0, self._after_member_change, ok, op, user_ids, name)

        threading.Thread(target=worker, daemon=True).start()

    def _after_member_change(self, ok, op, user_ids, name):
        self._set_busy(False)
        if ok:
            self.checked.difference_update(user_ids)
        self._load_members(pending=(op, user_ids, name) if ok else None)

    # ── helpers ──────────────────────────────────────────────────

    def _set_busy(self, busy):
        self.busy = busy
        state = "disabled" if busy else "normal"
        for btn in [self.new_btn, self.gdel_btn, self.grefresh_btn, self.madd_btn, self.mdel_btn]:
            btn.configure(state=state)


# ── Main frame ────────────────────────────────────────────────────────────────

class MainFrame(ctk.CTkFrame):
    def __init__(self, master, on_logout, logo_image=None):
        super().__init__(master, fg_color=C["bg"])
        self.on_logout   = on_logout
        self.logo_image  = logo_image
        self.tenant_name = ""
        self.token       = ""
        self.users         = []
        self.user_map      = {}    # treeview iid -> user dict
        self.checked_iids  = set()
        self.row_base_tag  = {}    # treeview iid -> "odd"|"even"
        self._hover_iid    = None
        self.is_running    = False
        self._build()

    # ── public ───────────────────────────────────────────────────

    def load(self, tenant_name, token, users):
        self.tenant_name = tenant_name
        self.token = token
        self.users = users
        self.tenant_lbl.configure(text=f"{tenant_name}.goskope.com")
        self._render_table(users)
        self._chip("READY", "#132238", "#93C5FD")
        self.view_tabs.set("사용자 관리")
        self._switch_view("사용자 관리")

    # ── layout ───────────────────────────────────────────────────

    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._build_topbar()
        self._build_body()
        copyright_label(self).grid(row=2, column=0, pady=(0, 8))

    def _build_topbar(self):
        bar = ctk.CTkFrame(
            self, fg_color=C["card"], corner_radius=0,
            border_width=0, height=60
        )
        bar.grid(row=0, column=0, sticky="ew")
        bar.grid_columnconfigure(1, weight=1)
        bar.grid_propagate(False)

        if self.logo_image:
            ctk.CTkLabel(bar, text="", image=self.logo_image).grid(
                row=0, column=0, padx=(18, 10), pady=8
            )

        self.tenant_lbl = ctk.CTkLabel(
            bar, text="",
            font=ctk.CTkFont(family="맑은 고딕", size=14, weight="bold"),
            text_color=C["text"]
        )
        self.tenant_lbl.grid(row=0, column=1, sticky="w", padx=4)

        self.view_tabs = ctk.CTkSegmentedButton(
            bar,
            values=["사용자 관리", "그룹 관리"],
            command=self._switch_view,
            font=ctk.CTkFont(family="맑은 고딕", size=12, weight="bold"),
            height=32,
            fg_color="#1F2A44",
            selected_color=C["accent"],
            selected_hover_color=C["accent2"],
            unselected_color="#1F2A44",
            unselected_hover_color="#2A3A5A",
            text_color=C["text"],
        )
        self.view_tabs.set("사용자 관리")
        self.view_tabs.grid(row=0, column=2, padx=(0, 12))

        self.status_chip = ctk.CTkLabel(
            bar, text="READY", width=86, height=26,
            corner_radius=13, fg_color="#132238", text_color="#93C5FD",
            font=ctk.CTkFont(size=11, weight="bold")
        )
        self.status_chip.grid(row=0, column=3, padx=(0, 12))

        ctk.CTkButton(
            bar, text="로그아웃", width=88, height=32,
            corner_radius=10, fg_color="#334155", hover_color="#475569",
            font=ctk.CTkFont(family="맑은 고딕", size=12, weight="bold"),
            command=self.on_logout
        ).grid(row=0, column=4, padx=(0, 18))

    def _build_body(self):
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew", padx=18, pady=14)
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(0, weight=3)   # 사용자 / 그룹 화면
        body.grid_rowconfigure(1, weight=1)   # log

        self.user_view = ctk.CTkFrame(body, fg_color="transparent")
        self.user_view.grid(row=0, column=0, sticky="nsew")
        self.user_view.grid_columnconfigure(0, weight=1)
        self.user_view.grid_rowconfigure(2, weight=1)   # table

        self._build_toolbar(self.user_view)
        self._build_filter_bar(self.user_view)
        self._build_table(self.user_view)
        self._build_log(body)

        self.group_view = GroupFrame(body, main_frame=self, log_cb=self.log,
                                     logo_image=self.logo_image)
        self.group_view.grid(row=0, column=0, sticky="nsew")
        self.group_view.grid_remove()

    def _build_toolbar(self, parent):
        bar = ctk.CTkFrame(
            parent, fg_color=C["card"], corner_radius=14,
            border_width=1, border_color=C["border"], height=60
        )
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        bar.grid_columnconfigure(2, weight=1)   # spacer
        bar.grid_propagate(False)

        # left: select-all + count
        self.sel_all_var = tk.BooleanVar(value=False)
        self.sel_all_cb = ctk.CTkCheckBox(
            bar, text="전체 선택",
            variable=self.sel_all_var, command=self._toggle_all,
            font=ctk.CTkFont(family="맑은 고딕", size=12),
            text_color=C["text"],
            fg_color=C["accent"], hover_color=C["accent2"],
            checkbox_width=18, checkbox_height=18
        )
        self.sel_all_cb.grid(row=0, column=0, padx=(16, 10))

        self.count_lbl = ctk.CTkLabel(
            bar, text="0명",
            font=ctk.CTkFont(family="맑은 고딕", size=12),
            text_color=C["sub"]
        )
        self.count_lbl.grid(row=0, column=1, padx=(0, 10))

        # spacer at col 2

        # right: action buttons
        self.refresh_btn = self._tb_btn(
            bar, "새로고침", "#1E3A5F", "#1D4ED8", self._refresh, col=3
        )
        self.add_btn = self._tb_btn(
            bar, "+ 사용자 추가", "#1D4ED8", "#1E40AF", self._open_add, col=4
        )
        self.csv_btn = self._tb_btn(
            bar, "CSV 일괄 추가", "#0F766E", "#0D9488", self._import_csv, col=5
        )
        self._tb_btn(
            bar, "예시 CSV", "#334155", "#475569", lambda: save_sample_csv(self), col=6, width=90
        )
        self.del_btn = self._tb_btn(
            bar, "선택 삭제", "#991B1B", "#B91C1C", self._delete_selected, col=7
        )

    def _tb_btn(self, parent, text, fg, hover, cmd, col, width=110):
        btn = ctk.CTkButton(
            parent, text=text, width=width, height=36,
            corner_radius=10, fg_color=fg, hover_color=hover,
            font=ctk.CTkFont(family="맑은 고딕", size=12, weight="bold"),
            command=cmd
        )
        btn.grid(row=0, column=col, padx=(0, 8 if col < 7 else 16))
        return btn

    def _build_filter_bar(self, parent):
        bar = ctk.CTkFrame(
            parent, fg_color=C["card"], corner_radius=14,
            border_width=1, border_color=C["border"], height=58
        )
        bar.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        bar.grid_columnconfigure(0, weight=1)
        bar.grid_columnconfigure(1, weight=1)
        bar.grid_propagate(False)

        def fentry(placeholder, col):
            e = ctk.CTkEntry(
                bar, height=36, corner_radius=10,
                border_width=1, border_color=C["border"],
                fg_color="#0B1220", text_color=C["text"],
                placeholder_text=placeholder,
                font=ctk.CTkFont(family="맑은 고딕", size=12),
            )
            e.grid(row=0, column=col, sticky="ew", padx=(14 if col == 0 else 6, 8), pady=11)
            return e

        self.filter_email = fentry("🔍  이메일 검색", 0)
        self.filter_name  = fentry("🔍  성 또는 이름 검색", 1)

        self.filter_status = ctk.CTkSegmentedButton(
            bar,
            values=["전체", "활성", "비활성"],
            command=self._apply_filter,
            font=ctk.CTkFont(family="맑은 고딕", size=12),
            height=36,
            fg_color="#1F2A44",
            selected_color=C["accent"],
            selected_hover_color=C["accent2"],
            unselected_color="#1F2A44",
            unselected_hover_color="#2A3A5A",
            text_color=C["text"],
        )
        self.filter_status.set("전체")
        self.filter_status.grid(row=0, column=2, padx=(0, 8))

        ctk.CTkButton(
            bar, text="↺  초기화", width=90, height=36,
            corner_radius=10, fg_color="#1F2A44", hover_color="#2A3A5A",
            font=ctk.CTkFont(family="맑은 고딕", size=12, weight="bold"),
            text_color=C["sub"],
            command=self._reset_filter
        ).grid(row=0, column=3, padx=(0, 14))

        self.filter_email.bind("<KeyRelease>", self._apply_filter)
        self.filter_name.bind("<KeyRelease>",  self._apply_filter)

    def _build_table(self, parent):
        card = ctk.CTkFrame(
            parent, fg_color=C["card"], corner_radius=14,
            border_width=1, border_color=C["border"]
        )
        card.grid(row=2, column=0, sticky="nsew", pady=(0, 10))
        card.grid_columnconfigure(0, weight=1)
        card.grid_rowconfigure(0, weight=1)

        # ─ 다크 스타일 ─
        style = ttk.Style()
        style.theme_use("default")

        style.configure("Dark.Treeview",
            background=C["row_odd"],
            foreground=C["text"],
            rowheight=38,
            fieldbackground=C["row_odd"],
            borderwidth=0,
            font=("맑은 고딕", 12),
        )
        style.configure("Dark.Treeview.Heading",
            background="#0A1628",
            foreground=C["sub"],
            relief="flat",
            font=("맑은 고딕", 12, "bold"),
            padding=(8, 6),
        )
        style.map("Dark.Treeview",
            background=[("selected", C["row_odd"])],
            foreground=[("selected", C["text"])],
        )
        style.map("Dark.Treeview.Heading",
            background=[("active", "#0F1E3A")],
            relief=[("active", "flat")],
        )

        # 스크롤바 다크 스타일
        style.configure("Dark.Vertical.TScrollbar",
            gripcount=0,
            background="#1E2A3E",
            darkcolor="#070B14",
            lightcolor="#070B14",
            troughcolor="#070B14",
            bordercolor="#070B14",
            arrowcolor="#3A4A66",
            borderwidth=0,
            relief="flat",
            width=10,
        )
        style.map("Dark.Vertical.TScrollbar",
            background=[("active", "#2A3A5A"), ("pressed", C["accent"]), ("!active", "#1E2A3E")],
            arrowcolor=[("active", "#93C5FD"),  ("!active", "#3A4A66")],
        )

        # ─ Treeview ─
        self.tree = ttk.Treeview(
            card,
            columns=("check", "email", "family", "given", "active"),
            show="headings",
            style="Dark.Treeview",
            selectmode="none",
        )
        self.tree.heading("check",  text="")
        self.tree.heading("email",  text="이메일 (userName)")
        self.tree.heading("family", text="성 (familyName)")
        self.tree.heading("given",  text="이름 (givenName)")
        self.tree.heading("active", text="상태")

        self.tree.column("check",  stretch=False, width=44,     anchor="center")
        self.tree.column("email",  stretch=True,  minwidth=200, anchor="w")
        self.tree.column("family", stretch=False, width=150,    anchor="w")
        self.tree.column("given",  stretch=False, width=150,    anchor="w")
        self.tree.column("active", stretch=False, width=90,     anchor="center")

        self.tree.tag_configure("odd",   background=C["row_odd"],  foreground=C["text"])
        self.tree.tag_configure("even",  background=C["row_even"], foreground=C["text"])
        self.tree.tag_configure("hover", background="#162540",     foreground=C["text"])

        self.tree.bind("<Button-1>",  self._on_tree_click)
        self.tree.bind("<Motion>",    self._on_tree_hover)
        self.tree.bind("<Leave>",     self._on_tree_leave)
        self.tree.bind("<Configure>", lambda e: self.after(30, self._redraw_status))
        self.tree.bind("<MouseWheel>",lambda e: self.after(5,  self._redraw_status))

        # ─ 스크롤바 ─
        vsb = ttk.Scrollbar(
            card, orient="vertical",
            command=self.tree.yview,
            style="Dark.Vertical.TScrollbar"
        )

        def _ysc(*args):
            vsb.set(*args)
            self.after(1, self._redraw_status)

        self.tree.configure(yscrollcommand=_ysc)

        # ─ 상태 Canvas 오버레이 (active 컬럼 위에 덮어서 셀 단위 색상 구현) ─
        self._st_cv = tk.Canvas(card, bg=C["row_odd"], highlightthickness=0)
        self._st_cv.bind("<MouseWheel>", lambda e: (
            self.tree.event_generate("<MouseWheel>", delta=e.delta),
            self.after(5, self._redraw_status)
        ))

        card.grid_columnconfigure(1, weight=0, minsize=10)
        self.tree.grid(row=0, column=0, sticky="nsew", padx=(1, 0), pady=1)
        vsb.grid(row=0, column=1, sticky="ns", pady=1, padx=(2, 2))

    def _build_log(self, parent):
        card = ctk.CTkFrame(
            parent, fg_color=C["card2"], corner_radius=14,
            border_width=1, border_color=C["border"]
        )
        card.grid(row=1, column=0, sticky="nsew")
        card.grid_columnconfigure(0, weight=1)
        card.grid_rowconfigure(1, weight=1)

        hdr = ctk.CTkFrame(card, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=18, pady=(12, 4))
        hdr.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            hdr, text="실행 로그",
            font=ctk.CTkFont(family="맑은 고딕", size=14, weight="bold"),
            text_color=C["text"]
        ).grid(row=0, column=0, sticky="w")

        self.summary_lbl = ctk.CTkLabel(
            hdr, text="",
            font=ctk.CTkFont(family="맑은 고딕", size=12),
            text_color=C["sub"]
        )
        self.summary_lbl.grid(row=0, column=1, sticky="e", padx=(0, 10))

        ctk.CTkButton(
            hdr, text="지우기", width=76, height=28,
            corner_radius=8, fg_color="#334155", hover_color="#475569",
            font=ctk.CTkFont(family="맑은 고딕", size=11, weight="bold"),
            command=self._clear_log
        ).grid(row=0, column=2, sticky="e")

        self.log_box = ctk.CTkTextbox(
            card, corner_radius=10,
            fg_color="#020617", border_width=1, border_color="#111C34",
            text_color="#D1D5DB",
            font=ctk.CTkFont(family="Consolas", size=11),
            wrap="word"
        )
        self.log_box.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 14))

    # ── table rendering ───────────────────────────────────────────

    def _render_table(self, users):
        self.tree.delete(*self.tree.get_children())
        self.user_map     = {}
        self.row_base_tag = {}
        self._hover_iid   = None
        self.sel_all_var.set(False)
        self.count_lbl.configure(text=f"{len(users)}명")

        for idx, user in enumerate(users):
            name_obj = user.get("name", {})
            active   = user.get("active", False)
            uid      = user.get("id", "")
            base_tag = "odd" if idx % 2 == 0 else "even"
            tag      = f"{base_tag}_active" if active else f"{base_tag}_inactive"
            checked  = "☑" if uid in self.checked_iids else "☐"

            iid = self.tree.insert("", "end",
                values=(
                    checked,
                    user.get("userName", ""),
                    name_obj.get("familyName", ""),
                    name_obj.get("givenName",  ""),
                    "● 활성" if active else "● 비활성",
                ),
                tags=(tag,),
            )
            self.user_map[iid]     = user
            self.row_base_tag[iid] = tag

    # ── actions ───────────────────────────────────────────────────

    def _on_tree_hover(self, event):
        iid = self.tree.identify_row(event.y)
        if iid == self._hover_iid:
            return
        if self._hover_iid and self._hover_iid in self.row_base_tag:
            self.tree.item(self._hover_iid, tags=(self.row_base_tag[self._hover_iid],))
        if iid and iid in self.user_map:
            self.tree.item(iid, tags=("hover",))
        self._hover_iid = iid

    def _on_tree_leave(self, event):
        if self._hover_iid and self._hover_iid in self.row_base_tag:
            self.tree.item(self._hover_iid, tags=(self.row_base_tag[self._hover_iid],))
        self._hover_iid = None

    def _on_tree_click(self, event):
        """체크 컬럼 클릭 시 해당 행 토글"""
        region = self.tree.identify_region(event.x, event.y)
        col    = self.tree.identify_column(event.x)
        iid    = self.tree.identify_row(event.y)
        if region == "cell" and col == "#1" and iid:
            self._toggle_check(iid)

    def _toggle_check(self, iid):
        user = self.user_map.get(iid)
        if not user:
            return
        uid = user.get("id", "")
        vals = list(self.tree.item(iid, "values"))
        if uid in self.checked_iids:
            self.checked_iids.discard(uid)
            vals[0] = "☐"
        else:
            self.checked_iids.add(uid)
            vals[0] = "☑"
        self.tree.item(iid, values=vals)

    def _toggle_all(self):
        all_iids = self.tree.get_children()
        if self.sel_all_var.get():
            for iid in all_iids:
                user = self.user_map.get(iid)
                if user:
                    self.checked_iids.add(user.get("id", ""))
                vals = list(self.tree.item(iid, "values"))
                vals[0] = "☑"
                self.tree.item(iid, values=vals)
        else:
            for iid in all_iids:
                user = self.user_map.get(iid)
                if user:
                    self.checked_iids.discard(user.get("id", ""))
                vals = list(self.tree.item(iid, "values"))
                vals[0] = "☐"
                self.tree.item(iid, values=vals)

    def _refresh(self):
        if self.is_running:
            return
        self._set_running(True)
        self.log("사용자 목록 새로고침 중...")

        def worker():
            users = get_all_scim_users(self.tenant_name, self.token, self.log)
            self.after(0, self._on_refresh, users)

        threading.Thread(target=worker, daemon=True).start()

    def _apply_filter(self, *_):
        email_q  = self.filter_email.get().strip().lower()
        name_q   = self.filter_name.get().strip().lower()
        status_q = self.filter_status.get()

        filtered = []
        for user in self.users:
            if email_q and email_q not in user.get("userName", "").lower():
                continue
            if name_q:
                name_obj = user.get("name", {})
                family   = name_obj.get("familyName", "").lower()
                given    = name_obj.get("givenName",  "").lower()
                if name_q not in family and name_q not in given:
                    continue
            if status_q == "활성"   and not user.get("active", False):
                continue
            if status_q == "비활성" and     user.get("active", False):
                continue
            filtered.append(user)

        self._render_table(filtered)

    def _reset_filter(self):
        self.filter_email.delete(0, "end")
        self.filter_name.delete(0, "end")
        self.filter_status.set("전체")
        self._render_table(self.users)

    def _on_refresh(self, users):
        self._set_running(False)
        if users is None:
            self.log("오류: 사용자 목록을 불러오지 못했습니다.")
            return
        self.users = users
        self._apply_filter()
        self.log(f"새로고침 완료 — {len(users)}명")

    def _open_add(self):
        if self.is_running:
            return
        AddUserDialog(
            self,
            tenant_name=self.tenant_name,
            token=self.token,
            on_success=self._refresh,
            log_cb=self.log
        )

    def _switch_view(self, name):
        if name == "그룹 관리":
            self.user_view.grid_remove()
            self.group_view.grid()
            self.group_view.show(self.tenant_name, self.token)
        else:
            self.group_view.grid_remove()
            self.user_view.grid()

    def _import_csv(self):
        if self.is_running:
            return
        path = filedialog.askopenfilename(
            title="CSV 파일 선택",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )
        if not path:
            return

        self._set_running(True)
        self.log(f"CSV 일괄 추가: {path}")

        def done(result):
            self.after(0, self._on_csv_done, result)

        threading.Thread(
            target=create_users_from_csv,
            kwargs={
                "tenant_name": self.tenant_name,
                "token": self.token,
                "csv_path": path,
                "log_callback": self.log,
                "done_callback": done
            },
            daemon=True
        ).start()

    def _on_csv_done(self, result):
        s  = result.get("success", 0)
        f  = result.get("fail",    0)
        sk = result.get("skip",    0)
        self.summary_lbl.configure(text=f"성공 {s} / 실패 {f} / 건너뜀 {sk}")
        self.is_running = False
        self._refresh()

    def _delete_selected(self):
        if self.is_running:
            return

        targets = [
            u for u in self.users
            if u.get("id", "") in self.checked_iids
        ]
        if not targets:
            CustomDialog(self, "선택 없음", "삭제할 사용자를 선택해주세요.", "warning",
                         logo_image=self.logo_image).show()
            return

        preview = "\n".join(u.get("userName", "?") for u in targets[:10])
        if len(targets) > 10:
            preview += f"\n... 외 {len(targets) - 10}명"

        if not CustomDialog(
            self,
            "삭제 확인",
            f"{len(targets)}명을 삭제하시겠습니까?\n\n{preview}\n\n이 작업은 되돌릴 수 없습니다.",
            "confirm",
            logo_image=self.logo_image
        ).confirm():
            return

        self._set_running(True)

        def done(result):
            self.after(0, self._on_delete_done, result)

        threading.Thread(
            target=delete_scim_users,
            kwargs={
                "tenant_name": self.tenant_name,
                "token": self.token,
                "users": targets,
                "log_callback": self.log,
                "done_callback": done
            },
            daemon=True
        ).start()

    def _on_delete_done(self, result):
        s = result.get("success", 0)
        f = result.get("fail",    0)
        self.summary_lbl.configure(text=f"삭제 성공 {s} / 실패 {f}")
        self.checked_iids.clear()
        self.sel_all_var.set(False)
        self.is_running = False
        self._refresh()

    # ── helpers ───────────────────────────────────────────────────

    def _set_running(self, running):
        self.is_running = running
        state = "disabled" if running else "normal"
        for btn in [self.refresh_btn, self.add_btn, self.csv_btn, self.del_btn]:
            btn.configure(state=state)
        if running:
            self._chip("RUNNING", "#3B1D12", "#FDBA74")
        else:
            self._chip("READY",   "#132238", "#93C5FD")

    def _chip(self, text, fg, tc):
        self.status_chip.configure(text=text, fg_color=fg, text_color=tc)

    def log(self, message):
        self.after(0, self._append, message)

    def _append(self, message):
        self.log_box.insert("end", message + "\n")
        self.log_box.see("end")

    def _clear_log(self):
        if not self.is_running:
            self.log_box.delete("1.0", "end")
            self.summary_lbl.configure(text="")


# ── App shell ─────────────────────────────────────────────────────────────────

class ScimUserApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self.title("SCIM 사용자 관리 툴")
        self.configure(fg_color=C["bg"])
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._icon_ref = None
        logo = self._load_logo()
        self._setup_icon()

        self.login = LoginFrame(self, on_connect=self._go_main, logo_image=logo)
        self.main  = MainFrame(self, on_logout=self._go_login, logo_image=logo)

        self._go_login()

    # ── navigation ───────────────────────────────────────────────

    def _go_login(self):
        self._fit_to_screen(580, 560)
        self.resizable(False, False)
        self.main.grid_remove()
        self.login.grid(row=0, column=0, sticky="nsew")

    def _go_main(self, tenant_name, token, users):
        w, h = self._fit_to_screen(1260, 880)
        self.resizable(True, True)
        self.minsize(min(960, w), min(700, h))
        self.login.grid_remove()
        self.main.load(tenant_name, token, users)
        self.main.grid(row=0, column=0, sticky="nsew")

    def _fit_to_screen(self, w, h):
        """작업 표시줄·제목줄에 가리지 않도록 화면 안에 맞추고 가운데 배치"""
        scale = ctk.ScalingTracker.get_window_scaling(self)
        sw = int(self.winfo_screenwidth()  / scale)
        sh = int(self.winfo_screenheight() / scale) - 100   # 작업 표시줄 + 제목줄 여유
        w, h = min(w, sw - 40), min(h, sh)
        x = (sw - w) // 2
        y = max((sh - h) // 2, 0)
        self.geometry(f"{w}x{h}+{x}+{y}")
        return w, h

    # ── icon / logo ───────────────────────────────────────────────

    def _load_logo(self):
        for path in self._icon_candidates():
            if os.path.exists(path):
                try:
                    img = Image.open(path)
                    return ctk.CTkImage(light_image=img, dark_image=img, size=(46, 46))
                except Exception:
                    pass
        return None

    def _setup_icon(self):
        for path in self._icon_candidates():
            if not os.path.exists(path):
                continue
            try:
                pil = Image.open(path)
                if path.lower().endswith(".ico"):
                    self.iconbitmap(path)
                else:
                    tmp = resource_path("netskope_runtime.ico")
                    pil.convert("RGBA").save(
                        tmp, format="ICO",
                        sizes=[(16, 16), (32, 32), (48, 48), (64, 64)]
                    )
                    self.iconbitmap(tmp)

                buf = io.BytesIO()
                pil.save(buf, format="PNG")
                photo = tk.PhotoImage(data=buf.getvalue())
                self.iconphoto(True, photo)
                self._icon_ref = photo
            except Exception:
                pass
            break

    @staticmethod
    def _icon_candidates():
        return [
            resource_path("netskope.ico"),
            resource_path("netskope_app.ico"),
            resource_path("netskope.png"),
            resource_path("netskope.jpg"),
            resource_path("netskope.jpeg"),
        ]


if __name__ == "__main__":
    app = ScimUserApp()
    app.mainloop()
