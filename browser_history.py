# browser_professional_gui.py
import mysql.connector
from mysql.connector import Error
from datetime import datetime
import webbrowser
import traceback
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

# ---------------- CONFIG ----------------
DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "0000",           # your MySQL password
    "database": "Browser_history" # your existing DB
}
RECENT_LOAD = 500  # increase if you want more rows in session

# ---------------- logging helper ----------------
def log_exc():
    print("----- EXCEPTION -----")
    traceback.print_exc()
    print("----- /EXCEPTION -----")

# ---------------- doubly-linked session ----------------
class Node:
    def __init__(self, hid, url, title, visited_at):
        self.id = hid
        self.url = url
        self.title = title
        self.visited_at = visited_at
        self.prev = None
        self.next = None

class BrowserSession:
    def __init__(self):
        self.head = None
        self.tail = None
        self.current = None

    def append(self, node):
        if not self.head:
            self.head = self.tail = node
        else:
            self.tail.next = node
            node.prev = self.tail
            self.tail = node
        self.current = node

    def remove_forward(self):
        if not self.current:
            return
        p = self.current.next
        while p:
            nxt = p.next
            p.prev = p.next = None
            p = nxt
        self.current.next = None
        self.tail = self.current

    def back(self):
        if self.current and self.current.prev:
            self.current = self.current.prev
            return True
        return False

    def forward(self):
        if self.current and self.current.next:
            self.current = self.current.next
            return True
        return False

    def remove_nodes_by_ids(self, id_set):
        p = self.head
        while p:
            nxt = p.next
            if p.id in id_set:
                if p.prev:
                    p.prev.next = p.next
                else:
                    self.head = p.next
                if p.next:
                    p.next.prev = p.prev
                else:
                    self.tail = p.prev
                if self.current == p:
                    self.current = p.prev or p.next
                p.prev = p.next = None
            p = nxt

# ---------------- DB helpers ----------------
def connect_db():
    return mysql.connector.connect(**DB_CONFIG)

def ensure_user(conn):
    cur = conn.cursor()
    cur.execute("SELECT user_id, user_name FROM `user` LIMIT 1")
    r = cur.fetchone()
    cur.close()
    if not r:
        raise RuntimeError("No user found in `user` table. Insert at least one user.")
    return r[0], r[1]

def load_recent_history(conn, user_id, limit):
    cur = conn.cursor()
    cur.execute("""
        SELECT history_id, url, IFNULL(title,''), visited_at
        FROM history
        WHERE user_id=%s
        ORDER BY visited_at ASC
        LIMIT %s
    """, (user_id, limit))
    rows = cur.fetchall()
    cur.close()
    sess = BrowserSession()
    for hid, url, title, visited_at in rows:
        sess.append(Node(hid, url, title, visited_at))
    return sess

def insert_history(conn, user_id, url, title, visited_at):
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO history (user_id, url, title, visited_at)
        VALUES (%s, %s, %s, %s)
    """, (user_id, url, title, visited_at))
    conn.commit()
    hid = cur.lastrowid
    cur.close()
    return hid

def search_history(conn, user_id, term, limit=500):
    cur = conn.cursor()
    like = f"%{term}%"
    cur.execute("""
        SELECT history_id, url, IFNULL(title,''), visited_at
        FROM history
        WHERE user_id=%s AND (LOWER(url) LIKE LOWER(%s) OR LOWER(IFNULL(title,'')) LIKE LOWER(%s))
        ORDER BY visited_at DESC
        LIMIT %s
    """, (user_id, like, like, limit))
    rows = cur.fetchall()
    cur.close()
    return rows

def add_bookmark(conn, user_id, url, title, history_id):
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO bookmarks (user_id, url, title, history_id)
        VALUES (%s, %s, %s, %s)
    """, (user_id, url, title, history_id))
    conn.commit()
    cur.close()

def list_bookmarks(conn, user_id):
    cur = conn.cursor()
    cur.execute("""
        SELECT bookmark_id, url, IFNULL(title,''), created_at
        FROM bookmarks
        WHERE user_id=%s
        ORDER BY created_at DESC
    """, (user_id,))
    rows = cur.fetchall()
    cur.close()
    return rows

def delete_history_by_ids(conn, ids):
    if not ids:
        return
    cur = conn.cursor()
    placeholders = ",".join(["%s"] * len(ids))
    cur.execute(f"DELETE FROM history WHERE history_id IN ({placeholders})", tuple(ids))
    conn.commit()
    cur.close()

def get_history_ids_before(conn, user_id, date_str):
    cur = conn.cursor()
    cur.execute("""
        SELECT history_id FROM history
        WHERE user_id=%s AND visited_at < %s
    """, (user_id, date_str + " 00:00:00"))
    rows = [r[0] for r in cur.fetchall()]
    cur.close()
    return rows

def get_last_n_history_ids(conn, user_id, n):
    cur = conn.cursor()
    cur.execute("""
        SELECT history_id FROM history
        WHERE user_id=%s
        ORDER BY visited_at DESC
        LIMIT %s
    """, (user_id, n))
    rows = [r[0] for r in cur.fetchall()]
    cur.close()
    return rows

# Bookmark helper functions for bulk deletes
def delete_bookmarks_by_ids(conn, ids):
    if not ids:
        return
    cur = conn.cursor()
    placeholders = ",".join(["%s"] * len(ids))
    cur.execute(f"DELETE FROM bookmarks WHERE bookmark_id IN ({placeholders})", tuple(ids))
    conn.commit()
    cur.close()

def get_bookmark_ids_before(conn, user_id, date_str):
    cur = conn.cursor()
    cur.execute("""
        SELECT bookmark_id FROM bookmarks
        WHERE user_id=%s AND created_at < %s
    """, (user_id, date_str + " 00:00:00"))
    rows = [r[0] for r in cur.fetchall()]
    cur.close()
    return rows

def get_last_n_bookmark_ids(conn, user_id, n):
    cur = conn.cursor()
    cur.execute("""
        SELECT bookmark_id FROM bookmarks
        WHERE user_id=%s
        ORDER BY created_at DESC
        LIMIT %s
    """, (user_id, n))
    rows = [r[0] for r in cur.fetchall()]
    cur.close()
    return rows

# ---------------- UI Utility ----------------
def fmt_date(dt):
    if isinstance(dt, datetime):
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    return str(dt)

# ---------------- Professional GUI App ----------------
class BrowserProfessionalApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Browser History — Manager")
        self.geometry("1100x760")
        self.minsize(900, 650)

        # styles
        self.style = ttk.Style(self)
        try:
            self.style.theme_use("clam")
        except Exception:
            pass

        # connect DB
        try:
            self.conn = connect_db()
            self.user_id, self.user_name = ensure_user(self.conn)
        except Exception as e:
            log_exc()
            messagebox.showerror("Database error", f"Cannot connect / read DB: {e}")
            self.destroy()
            return

        # session
        self.session = load_recent_history(self.conn, self.user_id, RECENT_LOAD)

        # UI: menu, toolbar, navigation panel, main frames, status bar
        self.create_menu()
        self.create_toolbar()               # has proper Enter bindings & debounce search
        self.create_navigation_panel()      # visible back/forward stacks and current
        self.create_main_panes()
        self.create_status_bar()

        self.refresh_history_tree()
        self.refresh_bookmarks_tree()
        self.update_navigation_ui()
        self.update_status("Ready")

        # keyboard shortcuts
        self.bind_all("<Control-f>", lambda e: self.search_entry.focus_set())
        self.bind_all("<Control-r>", lambda e: self.refresh_all())
        self.bind_all("<Control-q>", lambda e: self.quit_app())

    def create_menu(self):
        menubar = tk.Menu(self)
        # File
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Refresh", command=self.refresh_all, accelerator="Ctrl+R")
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.quit_app, accelerator="Ctrl+Q")
        menubar.add_cascade(label="File", menu=file_menu)

        # Tools
        tools = tk.Menu(menubar, tearoff=0)
        tools.add_command(label="Clear all history...", command=self.clear_all_history)
        tools.add_command(label="Clear before date...", command=self.clear_before_dialog)
        tools.add_command(label="Clear last N...", command=self.clear_last_n_dialog)
        tools.add_separator()
        tools.add_command(label="Clear all bookmarks...", command=self.clear_all_bookmarks)
        tools.add_command(label="Clear bookmarks before...", command=self.clear_bookmarks_before_dialog)
        tools.add_command(label="Clear last N bookmarks...", command=self.clear_last_n_bookmarks_dialog)
        menubar.add_cascade(label="Tools", menu=tools)

        # Help
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="About", command=self.show_about)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.config(menu=menubar)

    def create_toolbar(self):
        toolbar = ttk.Frame(self, padding=(6, 4))
        toolbar.pack(side="top", fill="x")

        self.url_var = tk.StringVar()
        self.title_var = tk.StringVar()
        ttk.Label(toolbar, text="URL:").pack(side="left", padx=(4,2))
        self.url_entry = ttk.Entry(toolbar, textvariable=self.url_var, width=60)
        self.url_entry.pack(side="left", padx=(0,8))
        # Press Enter in URL -> Visit
        self.url_entry.bind("<Return>", lambda e: self.visit_current())

        ttk.Label(toolbar, text="Title:").pack(side="left", padx=(2,2))
        self.title_entry = ttk.Entry(toolbar, textvariable=self.title_var, width=30)
        self.title_entry.pack(side="left", padx=(0,8))
        # Press Enter in Title -> Visit
        self.title_entry.bind("<Return>", lambda e: self.visit_current())

        self.btn_visit = ttk.Button(toolbar, text="Visit", command=self.visit_current)
        self.btn_visit.pack(side="left", padx=4)
        self.btn_back = ttk.Button(toolbar, text="Back", command=self.do_back)
        self.btn_back.pack(side="left", padx=2)
        self.btn_forward = ttk.Button(toolbar, text="Forward", command=self.do_forward)
        self.btn_forward.pack(side="left", padx=2)
        self.btn_bookmark = ttk.Button(toolbar, text="Bookmark", command=self.bookmark_current)
        self.btn_bookmark.pack(side="left", padx=6)

        # search box
        ttk.Label(toolbar, text="Search:").pack(side="left", padx=(12,2))
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(toolbar, textvariable=self.search_var, width=30)
        self.search_entry.pack(side="left", padx=(0,4))
        # Debounced search on typing:
        self._search_after_id = None
        self.search_var.trace_add("write", lambda *a: self._on_search_typing())
        # Press Enter in search -> immediate search
        self.search_entry.bind("<Return>", lambda e: self.do_search())

        ttk.Button(toolbar, text="Refresh", command=self.refresh_all).pack(side="right", padx=6)

    # --- helper methods for debounced search ---
    def _on_search_typing(self):
        """Called on every keystroke; debounce actual search to avoid jumpy UI."""
        try:
            if self._search_after_id:
                self.after_cancel(self._search_after_id)
        except Exception:
            pass
        self._search_after_id = self.after(400, self._do_debounced_search)

    def _do_debounced_search(self):
        self._search_after_id = None
        term = self.search_var.get().strip()
        if term == "":
            self.refresh_history_tree()
            self.update_navigation_ui()
            return
        try:
            rows = search_history(self.conn, self.user_id, term, limit=500)
            formatted = []
            for hid, url, title, visited_at in rows:
                if isinstance(visited_at, datetime):
                    visited_at = fmt_date(visited_at)
                formatted.append((hid, visited_at, title or "-", url))
            self.refresh_history_tree(rows=formatted)
            self.update_status(f"Search: {len(formatted)} results", 2000)
            self.search_entry.focus_set()
        except Exception:
            log_exc()
            messagebox.showerror("Search failed", "See console.")

    def create_navigation_panel(self):
        """Shows current and the stacks for back/forward so user can SEE navigation state."""
        nav = ttk.Frame(self, padding=(8,6))
        nav.pack(fill="x", padx=8)

        # Current display
        self.current_label = ttk.Label(nav, text="Current: -", font=("Segoe UI", 10, "bold"))
        self.current_label.pack(anchor="w", pady=(0,4))

        # Two listboxes side by side: Back stack | Forward stack
        stacks = ttk.Frame(nav)
        stacks.pack(fill="x")

        left_frame = ttk.Frame(stacks)
        left_frame.pack(side="left", fill="both", expand=True, padx=(0,6))
        ttk.Label(left_frame, text="Back (older)").pack(anchor="w")
        self.back_list = tk.Listbox(left_frame, height=4)
        self.back_list.pack(fill="both", expand=True)
        self.back_list.bind("<Double-Button-1>", self.on_back_list_open)

        mid_frame = ttk.Frame(stacks, width=120)
        mid_frame.pack(side="left", fill="y", padx=6)
        ttk.Button(mid_frame, text="Back", command=self.do_back).pack(fill="x", pady=2)
        ttk.Button(mid_frame, text="Forward", command=self.do_forward).pack(fill="x", pady=2)
        ttk.Button(mid_frame, text="Go to selected", command=self.go_to_selected_from_lists).pack(fill="x", pady=2)

        right_frame = ttk.Frame(stacks)
        right_frame.pack(side="left", fill="both", expand=True, padx=(6,0))
        ttk.Label(right_frame, text="Forward (newer)").pack(anchor="w")
        self.forward_list = tk.Listbox(right_frame, height=4)
        self.forward_list.pack(fill="both", expand=True)
        self.forward_list.bind("<Double-Button-1>", self.on_forward_list_open)

    def create_main_panes(self):
        main_pane = ttk.PanedWindow(self, orient="horizontal")
        main_pane.pack(fill="both", expand=True, padx=8, pady=6)

        # Left: History
        left_frame = ttk.Frame(main_pane)
        main_pane.add(left_frame, weight=3)

        lbl = ttk.Label(left_frame, text="History", font=("Segoe UI", 11, "bold"))
        lbl.pack(anchor="w", padx=6, pady=(4,0))

        # Treeview for history
        cols = ("id", "date", "title", "url")
        self.history_tree = ttk.Treeview(left_frame, columns=cols, show="headings", selectmode="browse")
        self.history_tree.heading("id", text="ID", anchor="w")
        self.history_tree.column("id", width=60, anchor="w", stretch=False)
        self.history_tree.heading("date", text="Visited At", anchor="w")
        self.history_tree.column("date", width=160, anchor="w", stretch=False)
        self.history_tree.heading("title", text="Title", anchor="w")
        self.history_tree.column("title", width=300, anchor="w")
        self.history_tree.heading("url", text="URL", anchor="w")
        self.history_tree.column("url", width=400, anchor="w")

        self.history_tree.pack(fill="both", expand=True, padx=6, pady=(4,6))
        self.history_tree.bind("<Double-1>", self.open_selected_history)
        self.history_tree.bind("<Button-3>", self.history_context_menu)

        # Right: Bookmarks & actions
        right_frame = ttk.Frame(main_pane, width=320)
        main_pane.add(right_frame, weight=1)

        lbl2 = ttk.Label(right_frame, text="Bookmarks", font=("Segoe UI", 11, "bold"))
        lbl2.pack(anchor="w", padx=6, pady=(4,0))

        bcols = ("id", "title", "url", "created")
        self.bookmark_tree = ttk.Treeview(right_frame, columns=bcols, show="headings", selectmode="browse")
        self.bookmark_tree.heading("id", text="ID")
        self.bookmark_tree.column("id", width=60, anchor="w", stretch=False)
        self.bookmark_tree.heading("title", text="Title")
        self.bookmark_tree.column("title", width=160, anchor="w")
        self.bookmark_tree.heading("url", text="URL")
        self.bookmark_tree.column("url", width=200, anchor="w")
        self.bookmark_tree.heading("created", text="Created At")
        self.bookmark_tree.column("created", width=140, anchor="w", stretch=False)
        self.bookmark_tree.pack(fill="both", expand=True, padx=6, pady=(4,6))
        self.bookmark_tree.bind("<Double-1>", self.open_selected_bookmark)
        self.bookmark_tree.bind("<Button-3>", self.bookmark_context_menu)

        # bottom: small action buttons
        btns = ttk.Frame(right_frame)
        btns.pack(fill="x", padx=6, pady=(0,6))
        ttk.Button(btns, text="Add Bookmark (selected)", command=self.bookmark_selected).pack(fill="x")
        ttk.Button(btns, text="Refresh Bookmarks", command=self.refresh_bookmarks_tree).pack(fill="x", pady=4)

    def create_status_bar(self):
        status = ttk.Frame(self, relief="sunken")
        status.pack(side="bottom", fill="x")
        self.status_var = tk.StringVar()
        self.status_label = ttk.Label(status, textvariable=self.status_var, anchor="w")
        self.status_label.pack(side="left", padx=6)
        self.user_label = ttk.Label(status, text=f"User: {self.user_name}", anchor="e")
        self.user_label.pack(side="right", padx=6)

    def update_status(self, text, timeout_ms=None):
        self.status_var.set(text)
        if timeout_ms:
            self.after(timeout_ms, lambda: self.status_var.set(""))

    # ---------------- navigation UI helpers ----------------
    def build_back_stack(self):
        """Return list of nodes older than current (nearest first)."""
        result = []
        p = self.session.current.prev if self.session.current else None
        while p:
            result.append(p)
            p = p.prev
        return result  # nearest older first (top is immediate back)

    def build_forward_stack(self):
        """Return list of nodes newer than current (nearest first)."""
        result = []
        p = self.session.current.next if self.session.current else None
        while p:
            result.append(p)
            p = p.next
        return result

    def update_navigation_ui(self):
        # update current label
        cur = self.session.current
        if cur:
            self.current_label.config(text=f"Current: [{cur.id}] {cur.title or '-'} | {cur.url}")
        else:
            self.current_label.config(text="Current: -")

        # update listboxes
        self.back_list.delete(0, tk.END)
        for node in self.build_back_stack():
            display = f"[{node.id}] {node.visited_at} | {node.title or '-'}"
            self.back_list.insert(tk.END, display)

        self.forward_list.delete(0, tk.END)
        for node in self.build_forward_stack():
            display = f"[{node.id}] {node.visited_at} | {node.title or '-'}"
            self.forward_list.insert(tk.END, display)

        # enable/disable toolbar buttons
        if self.session.current and self.session.current.prev:
            self.btn_back.state(["!disabled"])
        else:
            self.btn_back.state(["disabled"])

        if self.session.current and self.session.current.next:
            self.btn_forward.state(["!disabled"])
        else:
            self.btn_forward.state(["disabled"])

    def go_to_selected_from_lists(self):
        sel = self.back_list.curselection()
        if sel:
            idx = sel[0]
            node = self.build_back_stack()[idx]
            self.session.current = node
            self.update_navigation_ui()
            self.update_status("Jumped to selected (back stack)", 2000)
            return
        sel = self.forward_list.curselection()
        if sel:
            idx = sel[0]
            node = self.build_forward_stack()[idx]
            self.session.current = node
            self.update_navigation_ui()
            self.update_status("Jumped to selected (forward stack)", 2000)
            return
        messagebox.showinfo("Go to selected", "Select an item in Back or Forward list.")

    def on_back_list_open(self, evt=None):
        sel = self.back_list.curselection()
        if not sel:
            return
        idx = sel[0]
        node = self.build_back_stack()[idx]
        self.session.current = node
        self.update_navigation_ui()
        self.update_status("Jumped to selected (back list)", 2000)

    def on_forward_list_open(self, evt=None):
        sel = self.forward_list.curselection()
        if not sel:
            return
        idx = sel[0]
        node = self.build_forward_stack()[idx]
        self.session.current = node
        self.update_navigation_ui()
        self.update_status("Jumped to selected (forward list)", 2000)

    # ---------------- actions ----------------
    def refresh_all(self):
        try:
            self.session = load_recent_history(self.conn, self.user_id, RECENT_LOAD)
            self.refresh_history_tree()
            self.refresh_bookmarks_tree()
            self.update_navigation_ui()
            self.update_status("Refreshed", 3000)
        except Exception as e:
            log_exc()
            messagebox.showerror("Refresh failed", str(e))

    def refresh_history_tree(self, rows=None):
        """If rows provided, show those (e.g. search results). Otherwise show session."""
        for r in self.history_tree.get_children():
            self.history_tree.delete(r)
        if rows is not None:
            data = rows
        else:
            data = []
            p = self.session.tail
            while p:
                data.append((p.id, fmt_date(p.visited_at), p.title or "-", p.url))
                p = p.prev
        for hid, visited_at, title, url in data:
            if isinstance(visited_at, datetime):
                visited_at = fmt_date(visited_at)
            self.history_tree.insert("", "end", iid=str(hid), values=(hid, visited_at, title, url))

    def refresh_bookmarks_tree(self):
        for r in self.bookmark_tree.get_children():
            self.bookmark_tree.delete(r)
        try:
            rows = list_bookmarks(self.conn, self.user_id)
            for bid, url, title, created_at in rows:
                self.bookmark_tree.insert("", "end", iid=f"b{bid}", values=(bid, title or "-", url, fmt_date(created_at)))
        except Exception as e:
            log_exc()
            messagebox.showerror("Bookmarks failed", str(e))

    def visit_current(self):
        url = self.url_var.get().strip()
        title = self.title_var.get().strip()
        if not url:
            messagebox.showwarning("Input required", "Please enter a URL.")
            return
        try:
            if self.session.current and self.session.current != self.session.tail:
                self.session.remove_forward()
            visited_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            hid = insert_history(self.conn, self.user_id, url, title, visited_at)
            node = Node(hid, url, title, visited_at)
            self.session.append(node)
            self.session.current = node
            self.url_var.set("")
            self.title_var.set("")
            self.refresh_history_tree()
            self.update_navigation_ui()
            self.update_status("Visited", 2000)
            webbrowser.open(url)
        except Exception as e:
            log_exc()
            messagebox.showerror("Visit failed", str(e))

    def do_back(self):
        if self.session.back():
            self.update_navigation_ui()
            self.update_status("Moved back", 2000)
            self.refresh_history_tree()
        else:
            self.update_status("Already at oldest entry", 2000)

    def do_forward(self):
        if self.session.forward():
            self.update_navigation_ui()
            self.update_status("Moved forward", 2000)
            self.refresh_history_tree()
        else:
            self.update_status("Already at newest entry", 2000)

    # ---------------- tree interactions ----------------
    def open_selected_history(self, event=None):
        sel = self.history_tree.selection()
        if not sel:
            return
        hid = int(sel[0])
        p = self.session.head
        while p:
            if p.id == hid:
                self.session.current = p
                break
            p = p.next
        else:
            cur = self.conn.cursor()
            cur.execute("SELECT history_id, url, IFNULL(title,''), visited_at FROM history WHERE history_id=%s", (hid,))
            r = cur.fetchone()
            cur.close()
            if r:
                hid, url, title, visited_at = r
                node = Node(hid, url, title, visited_at)
                self.session.append(node)
                self.session.current = node
        cur_node = self.session.current
        if cur_node:
            webbrowser.open(cur_node.url)
            try:
                visited_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                hid_new = insert_history(self.conn, self.user_id, cur_node.url, cur_node.title, visited_at)
                node = Node(hid_new, cur_node.url, cur_node.title, visited_at)
                self.session.append(node)
                self.refresh_history_tree()
                self.update_navigation_ui()
            except Exception:
                pass

    def open_selected_bookmark(self, event=None):
        sel = self.bookmark_tree.selection()
        if not sel:
            return
        iid = sel[0]
        bid = int(iid.lstrip("b"))
        cur = self.conn.cursor()
        cur.execute("SELECT url, IFNULL(title,'') FROM bookmarks WHERE bookmark_id=%s", (bid,))
        r = cur.fetchone()
        cur.close()
        if r:
            url, title = r
            webbrowser.open(url)
            try:
                visited_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                hid_new = insert_history(self.conn, self.user_id, url, title, visited_at)
                node = Node(hid_new, url, title, visited_at)
                self.session.append(node)
                self.refresh_history_tree()
                self.update_navigation_ui()
            except Exception:
                pass

    # ---------------- context menus ----------------
    def history_context_menu(self, event):
        iid = self.history_tree.identify_row(event.y)
        menu = tk.Menu(self, tearoff=0)
        if iid:
            menu.add_command(label="Open (in browser)", command=lambda: self._open_history_iid(iid))
            menu.add_command(label="Open & add history", command=lambda: self.open_selected_history())
            menu.add_command(label="Bookmark", command=lambda: self._bookmark_history_iid(iid))
            menu.add_separator()
            menu.add_command(label="Delete from DB", command=lambda: self._delete_history_iid(iid))
        else:
            menu.add_command(label="Refresh", command=self.refresh_all)
        menu.tk_popup(event.x_root, event.y_root)

    def bookmark_context_menu(self, event):
        iid = self.bookmark_tree.identify_row(event.y)
        menu = tk.Menu(self, tearoff=0)
        if iid:
            menu.add_command(label="Open (in browser)", command=lambda: self._open_bookmark_iid(iid))
            menu.add_command(label="Open & add history", command=self.open_selected_bookmark)
            menu.add_separator()
            menu.add_command(label="Delete bookmark", command=lambda: self._delete_bookmark_iid(iid))
        else:
            menu.add_command(label="Refresh", command=self.refresh_bookmarks_tree)
        menu.tk_popup(event.x_root, event.y_root)

    # ---------------- small helpers for context menu actions ----------------
    def _open_history_iid(self, iid):
        hid = int(iid)
        cur = self.conn.cursor()
        cur.execute("SELECT url FROM history WHERE history_id=%s", (hid,))
        r = cur.fetchone()
        cur.close()
        if r:
            url = r[0]
            webbrowser.open(url)
            self.update_status(f"Opened {url}", 3000)

    def _bookmark_history_iid(self, iid):
        hid = int(iid)
        cur = self.conn.cursor()
        cur.execute("SELECT url, IFNULL(title,'') FROM history WHERE history_id=%s", (hid,))
        r = cur.fetchone()
        cur.close()
        if not r:
            messagebox.showerror("Bookmark", "History row not found.")
            return
        url, title = r
        try:
            add_bookmark(self.conn, self.user_id, url, title, hid)
            self.refresh_bookmarks_tree()
            self.update_status("Bookmark added", 3000)
        except Exception:
            log_exc()
            messagebox.showerror("Bookmark", "Failed to add bookmark.")

    def _delete_history_iid(self, iid):
        hid = int(iid)
        if not messagebox.askyesno("Delete", f"Delete history row {hid}?"):
            return
        try:
            delete_history_by_ids(self.conn, [hid])
            self.session.remove_nodes_by_ids({hid})
            self.refresh_history_tree()
            self.update_navigation_ui()
            self.update_status("Deleted history row", 3000)
        except Exception:
            log_exc()
            messagebox.showerror("Delete failed", "See console.")

    def _open_bookmark_iid(self, iid):
        bid = int(iid.lstrip("b"))
        cur = self.conn.cursor()
        cur.execute("SELECT url FROM bookmarks WHERE bookmark_id=%s", (bid,))
        r = cur.fetchone()
        cur.close()
        if r:
            webbrowser.open(r[0])
            self.update_status("Opened bookmark", 2000)

    def _delete_bookmark_iid(self, iid):
        bid = int(iid.lstrip("b"))
        if not messagebox.askyesno("Delete", f"Delete bookmark {bid}?"):
            return
        try:
            delete_bookmarks_by_ids(self.conn, [bid])
            self.refresh_bookmarks_tree()
            self.update_status("Deleted bookmark", 3000)
        except Exception:
            log_exc()
            messagebox.showerror("Delete failed", "See console.")

    # ---------------- bookmark flow ----------------
    def bookmark_current(self):
        cur_node = self.session.current
        if not cur_node:
            messagebox.showinfo("Bookmark", "No current page.")
            return
        try:
            add_bookmark(self.conn, self.user_id, cur_node.url, cur_node.title, cur_node.id)
            self.refresh_bookmarks_tree()
            self.update_status("Bookmarked current", 3000)
        except Exception:
            log_exc()
            messagebox.showerror("Bookmark error", "See console.")

    def bookmark_selected(self):
        sel = self.history_tree.selection()
        if not sel:
            messagebox.showinfo("Bookmark", "Select a history row to bookmark.")
            return
        hid = int(sel[0])
        cur = self.conn.cursor()
        cur.execute("SELECT url, IFNULL(title,'') FROM history WHERE history_id=%s", (hid,))
        r = cur.fetchone()
        cur.close()
        if r:
            url, title = r
            try:
                add_bookmark(self.conn, self.user_id, url, title, hid)
                self.refresh_bookmarks_tree()
                self.update_status("Bookmarked selected row", 3000)
            except Exception:
                log_exc()
                messagebox.showerror("Bookmark error", "See console.")

    # ---------------- search ----------------
    def on_search_change(self):
        # kept for backward compatibility — debounced path is the primary flow
        term = self.search_var.get().strip()
        if not term:
            self.refresh_history_tree()
            return
        try:
            rows = search_history(self.conn, self.user_id, term, limit=500)
            formatted = []
            for hid, url, title, visited_at in rows:
                if isinstance(visited_at, datetime):
                    visited_at = fmt_date(visited_at)
                formatted.append((hid, visited_at, title or "-", url))
            self.refresh_history_tree(rows=formatted)
            self.update_status(f"Search: {len(formatted)} results", 2000)
        except Exception:
            log_exc()
            messagebox.showerror("Search failed", "See console.")

    def do_search(self):
        term = self.search_var.get().strip()
        if not term:
            self.refresh_history_tree()
            self.update_navigation_ui()
            return
        try:
            rows = search_history(self.conn, self.user_id, term, limit=500)
            formatted = []
            for hid, url, title, visited_at in rows:
                if isinstance(visited_at, datetime):
                    visited_at = fmt_date(visited_at)
                formatted.append((hid, visited_at, title or "-", url))
            self.refresh_history_tree(rows=formatted)
            self.update_status(f"Search: {len(formatted)} results", 3000)
            self.search_entry.focus_set()
        except Exception:
            log_exc()
            messagebox.showerror("Search failed", "See console.")

    # ---------------- clear history tools ----------------
    def clear_all_history(self):
        if not messagebox.askyesno("Clear all", "This will permanently delete ALL history for current user. Continue?"):
            return
        try:
            cur = self.conn.cursor()
            cur.execute("SELECT history_id FROM history WHERE user_id=%s", (self.user_id,))
            ids = [r[0] for r in cur.fetchall()]
            cur.close()
            if ids:
                delete_history_by_ids(self.conn, ids)
                self.session.remove_nodes_by_ids(set(ids))
                self.refresh_history_tree()
                self.update_navigation_ui()
                self.update_status("Cleared all history", 3000)
            else:
                self.update_status("No history to clear", 3000)
        except Exception:
            log_exc()
            messagebox.showerror("Clear failed", "See console.")

    def clear_before_dialog(self):
        date_str = simpledialog.askstring("Clear Before", "Enter date (YYYY-MM-DD):")
        if not date_str:
            return
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            messagebox.showerror("Invalid date", "Use YYYY-MM-DD")
            return
        try:
            ids = get_history_ids_before(self.conn, self.user_id, date_str)
            if not ids:
                messagebox.showinfo("Clear Before", "No records older than that date.")
                return
            if not messagebox.askyesno("Confirm", f"Delete {len(ids)} entries older than {date_str}?"):
                return
            delete_history_by_ids(self.conn, ids)
            self.session.remove_nodes_by_ids(set(ids))
            self.refresh_history_tree()
            self.update_navigation_ui()
            self.update_status(f"Deleted {len(ids)} rows older than {date_str}", 3000)
        except Exception:
            log_exc()
            messagebox.showerror("Clear failed", "See console.")

    def clear_last_n_dialog(self):
        n_str = simpledialog.askstring("Clear Last N", "Enter N (positive integer):")
        if not n_str:
            return
        try:
            n = int(n_str)
            if n <= 0:
                raise ValueError()
        except ValueError:
            messagebox.showerror("Invalid", "Enter a positive integer.")
            return
        try:
            ids = get_last_n_history_ids(self.conn, self.user_id, n)
            if not ids:
                messagebox.showinfo("Clear Last N", "No entries to delete.")
                return
            if not messagebox.askyesno("Confirm", f"Delete last {len(ids)} entries?"):
                return
            delete_history_by_ids(self.conn, ids)
            self.session.remove_nodes_by_ids(set(ids))
            self.refresh_history_tree()
            self.update_navigation_ui()
            self.update_status(f"Deleted {len(ids)} last entries", 3000)
        except Exception:
            log_exc()
            messagebox.showerror("Clear failed", "See console.")

    # ---------------- bookmark clear tools ----------------
    def clear_all_bookmarks(self):
        if not messagebox.askyesno("Clear all bookmarks", "Permanently delete ALL bookmarks for current user?"):
            return
        try:
            cur = self.conn.cursor()
            cur.execute("SELECT bookmark_id FROM bookmarks WHERE user_id=%s", (self.user_id,))
            ids = [r[0] for r in cur.fetchall()]
            cur.close()
            if ids:
                delete_bookmarks_by_ids(self.conn, ids)
                self.refresh_bookmarks_tree()
                self.update_status(f"Deleted {len(ids)} bookmarks", 3000)
            else:
                self.update_status("No bookmarks to delete", 3000)
        except Exception:
            log_exc()
            messagebox.showerror("Clear failed", "See console.")

    def clear_bookmarks_before_dialog(self):
        date_str = simpledialog.askstring("Clear Bookmarks Before", "Enter date (YYYY-MM-DD):")
        if not date_str:
            return
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            messagebox.showerror("Invalid date", "Use YYYY-MM-DD")
            return
        try:
            ids = get_bookmark_ids_before(self.conn, self.user_id, date_str)
            if not ids:
                messagebox.showinfo("Clear Bookmarks", "No bookmarks older than that date.")
                return
            if not messagebox.askyesno("Confirm", f"Delete {len(ids)} bookmarks older than {date_str}?"):
                return
            delete_bookmarks_by_ids(self.conn, ids)
            self.refresh_bookmarks_tree()
            self.update_status(f"Deleted {len(ids)} bookmarks older than {date_str}", 3000)
        except Exception:
            log_exc()
            messagebox.showerror("Clear failed", "See console.")

    def clear_last_n_bookmarks_dialog(self):
        n_str = simpledialog.askstring("Clear Last N Bookmarks", "Enter N (positive integer):")
        if not n_str:
            return
        try:
            n = int(n_str)
            if n <= 0:
                raise ValueError()
        except ValueError:
            messagebox.showerror("Invalid", "Enter a positive integer.")
            return
        try:
            ids = get_last_n_bookmark_ids(self.conn, self.user_id, n)
            if not ids:
                messagebox.showinfo("Clear Last N", "No bookmarks to delete.")
                return
            if not messagebox.askyesno("Confirm", f"Delete last {len(ids)} bookmarks?"):
                return
            delete_bookmarks_by_ids(self.conn, ids)
            self.refresh_bookmarks_tree()
            self.update_status(f"Deleted {len(ids)} last bookmarks", 3000)
        except Exception:
            log_exc()
            messagebox.showerror("Clear failed", "See console.")

    # ---------------- misc ----------------
    def show_about(self):
        messagebox.showinfo("About", "Browser History Manager\nProfessional GUI\n(Prototype)")

    def quit_app(self):
        try:
            self.conn.close()
        except Exception:
            pass
        self.destroy()

# ---------------- run ----------------
if __name__ == "__main__":
    app = BrowserProfessionalApp()
    if app.winfo_exists():
        app.mainloop()
