#!/usr/bin/env python3
"""Generates the 'Aughor Two Skins' canvas: one layout, two token sets.

Dark follows Databricks (Du Bois greys 900→500, blue for everything clickable, visible
borders, cards on a darker ground). Light follows Excel (white grid, grey chrome, Excel
green for selection and the primary, Good/Bad/Neutral cell fills, gridlines, a formula
bar and a status bar). Every screen is built by the SAME functions; only the token dict
changes, plus the few skin rules the dict carries (gridlines vs hairlines, sheet tabs vs
underlined tabs, cell fills vs pills).
"""
import json, os, datetime
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, 'project')
os.makedirs(OUT, exist_ok=True)

SANS = "Inter, system-ui, -apple-system, 'Segoe UI', sans-serif"
MONO = "'JetBrains Mono', ui-monospace, Menlo, monospace"
FONTS = '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&amp;family=JetBrains+Mono:wght@400;500&amp;display=swap">'
TAB = 'font-variant-numeric:tabular-nums;'

DARK = {
    'name': 'dark', 'excel': False, 'r': 4,
    'page': '#11171C', 'chrome': '#1F272D', 'card': '#1F272D', 'hover': '#26313A', 'sel': '#142E45',
    'code': '#0B1116', 'inp': '#11171C',
    'b0': '#253039', 'b1': '#2F3C47', 'b2': '#3F5162', 'b3': '#5F7281',
    't1': '#E8ECF0', 't2': '#92A4B3', 't3': '#8496A4', 't4': '#5F7281',
    'blue1': '#0E2A44', 'blue2': '#1F4A75', 'blue3': '#4299E0', 'blue4': '#8ACAFF',
    'grn1': '#14331F', 'grn2': '#1F5A33', 'grn3': '#3CAA60', 'grn4': '#8DDDA8',
    'amb1': '#3A2A10', 'amb2': '#6B4A1A', 'amb3': '#DE7921', 'amb4': '#F2BE88',
    'red1': '#3B1A21', 'red2': '#6E2536', 'red3': '#E65B77', 'red4': '#F792A6',
    'vio1': '#2A2140', 'vio2': '#4A3B70', 'vio3': '#9C7BDD', 'vio4': '#C0A9EE',
    'primary': '#2272B4', 'primaryHover': '#2A82C8', 'onPrimary': '#FFFFFF',
    'link': '#8ACAFF', 'accent': '#4299E0', 'accentText': '#8ACAFF',
    'segOn': '#34434F', 'segOnText': '#E8ECF0',
    'navActiveBg': '#142E45', 'navActiveText': '#E8ECF0', 'navBar': '',
    'headerBg': '#1F272D', 'ann': '#E0A84A',
}
LIGHT = {
    'name': 'light', 'excel': True, 'r': 3,
    'page': '#FFFFFF', 'chrome': '#F3F3F3', 'card': '#FFFFFF', 'hover': '#EBEBEB', 'sel': '#E6F2EB',
    'code': '#FAFAFA', 'inp': '#FFFFFF',
    'b0': '#E1E1E1', 'b1': '#D4D4D4', 'b2': '#C4C4C4', 'b3': '#8A8A8A',
    't1': '#1F1F1F', 't2': '#424242', 't3': '#616161', 't4': '#8A8A8A',
    'blue1': '#DDEBF7', 'blue2': '#9DC3E6', 'blue3': '#0F6CBD', 'blue4': '#0B5394',
    'grn1': '#C6EFCE', 'grn2': '#8FD3A8', 'grn3': '#1E7B45', 'grn4': '#006100',
    'amb1': '#FFEB9C', 'amb2': '#E6C35C', 'amb3': '#B25E00', 'amb4': '#9C5700',
    'red1': '#FFC7CE', 'red2': '#F09AA5', 'red3': '#C50F1F', 'red4': '#9C0006',
    'vio1': '#EADDF7', 'vio2': '#C9A9EA', 'vio3': '#6B3FA0', 'vio4': '#4B2C7F',
    'primary': '#107C41', 'primaryHover': '#0F703B', 'onPrimary': '#FFFFFF',
    'link': '#0F6CBD', 'accent': '#107C41', 'accentText': '#0C5E32',
    'segOn': '#E6F2EB', 'segOnText': '#0C5E32',
    'navActiveBg': '#FFFFFF', 'navActiveText': '#0C5E32', 'navBar': 'box-shadow:inset 3px 0 0 #107C41;',
    'headerBg': '#F3F3F3', 'ann': '#E0A84A',
}

# ── contrast ─────────────────────────────────────────────────────────────────
def lum(h):
    h = h.lstrip('#')
    r, g, b = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)

def cr(a, b):
    la, lb = lum(a), lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)

def ratio(a, b):
    return f'{cr(a, b):.2f}:1'

# ── icons (inline stroke SVG, never emoji) ───────────────────────────────────
ICONS = {
    'home': '<path d="M3 11 12 4l9 7v9H3z"></path>',
    'tray': '<path d="M4 12h5l2 3h2l2-3h5"></path><path d="M4 12v6h16v-6"></path>',
    'ask': '<path d="M4 5h16v11H9l-5 4z"></path>',
    'brief': '<path d="M6 3h9l4 4v14H6z"></path><path d="M9 12h6M9 16h6"></path>',
    'runs': '<circle cx="11" cy="11" r="7"></circle><path d="m20 20-3.5-3.5"></path>',
    'search': '<circle cx="11" cy="11" r="7"></circle><path d="m20 20-3.5-3.5"></path>',
    'catalog': '<ellipse cx="12" cy="6" rx="8" ry="3"></ellipse><path d="M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6"></path>',
    'sql': '<path d="m8 8-4 4 4 4M16 8l4 4-4 4"></path>',
    'semantic': '<path d="m12 3 9 5-9 5-9-5z"></path><path d="m3 13 9 5 9-5"></path>',
    'ontology': '<circle cx="12" cy="5" r="2"></circle><circle cx="5" cy="19" r="2"></circle><circle cx="19" cy="19" r="2"></circle><path d="M12 7v5l-7 5M12 12l7 5"></path>',
    'graph': '<path d="M4 19V5M4 19h16"></path><path d="m7 14 4-4 3 3 5-6"></path>',
    'actions': '<path d="M13 3 5 14h6l-1 7 8-11h-6z"></path>',
    'agents': '<circle cx="12" cy="8" r="4"></circle><path d="M4 21a8 8 0 0 1 16 0"></path>',
    'automations': '<path d="M4 12h6M14 12h6"></path><circle cx="12" cy="12" r="2"></circle>',
    'monitors': '<path d="M3 12h4l3-7 4 14 3-7h4"></path>',
    'departures': '<path d="M4 12h14M13 6l6 6-6 6"></path>',
    'spend': '<path d="M12 3v18M5 7h14"></path><path d="M3 13a2.5 2.5 0 0 0 5 0L5.5 7zM16 13a2.5 2.5 0 0 0 5 0L18.5 7z"></path>',
    'security': '<path d="M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6z"></path>',
    'evals': '<path d="m5 12 4 4L19 6"></path>',
    'settings': '<circle cx="12" cy="12" r="3"></circle><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1 7 17M17 7l2.1-2.1"></path>',
    'chev': '<path d="m6 9 6 6 6-6"></path>',
    'sun': '<circle cx="12" cy="12" r="4"></circle><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"></path>',
    'moon': '<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"></path>',
    'filter': '<path d="M3 5h18l-7 8v6l-4-2v-4z"></path>',
    'close': '<path d="M6 6l12 12M18 6 6 18"></path>',
    'more': '<circle cx="5" cy="12" r="1.5"></circle><circle cx="12" cy="12" r="1.5"></circle><circle cx="19" cy="12" r="1.5"></circle>',
    'sortdown': '<path d="M12 5v14M6 13l6 6 6-6"></path>',
    'plus': '<path d="M12 5v14M5 12h14"></path>',
    'check': '<path d="m5 12 4 4L19 6"></path>',
    'pause': '<path d="M8 5v14M16 5v14"></path>',
    'play': '<path d="M7 4v16l13-8z"></path>',
    'edit': '<path d="M4 20h4l10-10-4-4L4 16z"></path>',
    'ext': '<path d="M14 4h6v6M20 4l-9 9M18 14v6H4V6h6"></path>',
}

def svg(name, size=14, sw=1.6):
    return (f'<svg aria-hidden="true" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
            f'stroke="currentColor" stroke-width="{sw}" stroke-linecap="round" stroke-linejoin="round">{ICONS[name]}</svg>')

# ── primitives ───────────────────────────────────────────────────────────────
def btn(t, label, kind='secondary', extra='', aria=''):
    base = (f"height:28px;padding:0 12px;border-radius:{t['r']}px;font-family:{SANS};font-size:13px;font-weight:500;"
            f"display:inline-flex;align-items:center;gap:6px;white-space:nowrap;cursor:pointer;line-height:1;")
    if kind == 'primary':
        s = base + f"border:1px solid {t['primary']};background:{t['primary']};color:{t['onPrimary']};font-weight:600;"
    elif kind == 'ghost':
        s = base + f"border:1px solid transparent;background:transparent;color:{t['t2']};"
    elif kind == 'icon':
        s = (f"width:30px;height:30px;padding:0;border-radius:{t['r']}px;border:1px solid {t['b2']};background:{t['inp']};"
             f"color:{t['t2']};display:inline-flex;align-items:center;justify-content:center;cursor:pointer;position:relative;")
    else:
        s = base + f"border:1px solid {t['b2']};background:{t['inp']};color:{t['t1']};"
    a = f' aria-label="{aria}"' if aria else ''
    return f'<button{a} style="{s}{extra}">{label}</button>'

def seg(t, opts, active, width=None):
    items = []
    for i, o in enumerate(opts):
        on = o == active
        bl = f"border-left:1px solid {t['b2']};" if i else ""
        st = (f"background:{t['segOn']};color:{t['segOnText']};font-weight:600;" if on
              else f"background:transparent;color:{t['t2']};font-weight:400;")
        w = f"min-width:{width}px;" if width else ""
        items.append(f'<button aria-pressed="{"true" if on else "false"}" style="height:26px;padding:0 10px;border:0;{bl}{st}{w}'
                     f'font-size:13px;font-family:{SANS};cursor:pointer;line-height:1">{o}</button>')
    return (f'<div role="group" style="display:inline-flex;height:28px;border:1px solid {t["b2"]};border-radius:{t["r"]}px;'
            f'overflow:hidden;background:{t["inp"]}">{"".join(items)}</div>')

KINDS = {'good': ('grn1', 'grn2', 'grn4'), 'bad': ('red1', 'red2', 'red4'), 'warn': ('amb1', 'amb2', 'amb4'),
         'info': ('blue1', 'blue2', 'blue4'), 'deep': ('vio1', 'vio2', 'vio4'), 'neutral': (None, 'b2', 't2')}

def tag(t, text, kind='neutral', dot=False):
    bg, bd, fg = KINDS[kind]
    bgc = t[bg] if bg else (t['chrome'] if t['excel'] else t['inp'])
    d = f'<span style="width:7px;height:7px;border-radius:999px;background:{t[bd if bg else "t3"]}"></span>' if dot else ''
    if t['excel']:
        return (f'<span style="display:inline-flex;align-items:center;gap:6px;height:22px;padding:0 8px;border-radius:2px;'
                f'background:{bgc};color:{t[fg]};font-size:12px;font-weight:500;white-space:nowrap">{d}{text}</span>')
    return (f'<span style="display:inline-flex;align-items:center;gap:6px;height:22px;padding:0 8px;border-radius:{t["r"]}px;'
            f'border:1px solid {t[bd]};background:{bgc};color:{t[fg]};font-size:12px;font-weight:500;white-space:nowrap">{d}{text}</span>')

def label(t, text, extra=''):
    return f'<div style="font-size:12px;font-weight:600;color:{t["t3"]};{extra}">{text}</div>'

def dot(t, color):
    return f'<span style="width:7px;height:7px;border-radius:999px;background:{color};flex-shrink:0"></span>'

def sep(t):
    return f'<span aria-hidden="true" style="color:{t["t4"]}">·</span>'

# ── shell regions ────────────────────────────────────────────────────────────
def topbar(t, tray):
    theme_icon = 'sun' if t['name'] == 'dark' else 'moon'
    theme_aria = 'Switch to the light theme' if t['name'] == 'dark' else 'Switch to the dark theme'
    badge = (f'<span style="position:absolute;top:-6px;right:-6px;min-width:16px;height:16px;padding:0 4px;box-sizing:border-box;'
             f'border-radius:{t["r"]}px;background:{t["amb3"]};color:#1F1F1F;font-size:11px;font-weight:600;display:flex;'
             f'align-items:center;justify-content:center;line-height:1">{tray}</span>')
    return f'''<div style="position:relative;height:48px;flex-shrink:0;box-sizing:border-box;display:flex;align-items:center;gap:12px;padding:0 16px;background:{t['chrome']};border-bottom:1px solid {t['b1']}">
  <div style="font-family:{MONO};font-weight:600;font-size:13px;letter-spacing:0.08em;color:{t['t1']}">AUGHOR</div>
  {btn(t, 'Default ' + svg('chev', 12))}
  <div style="width:1px;height:20px;background:{t['b2']}"></div>
  <span style="font-size:12px;color:{t['t3']}">Connection</span>
  {btn(t, 'theLook ' + svg('chev', 12))}
  <div style="position:absolute;left:50%;top:9px;transform:translateX(-50%);width:480px;height:30px;box-sizing:border-box;display:flex;align-items:center;gap:8px;padding:0 10px;border-radius:{t['r']}px;border:1px solid {t['b2']};background:{t['inp']};color:{t['t3']}">
    {svg('search', 14)}
    <input aria-label="Search, ask, or run a command" placeholder="Search data, ask a question, or run a command" style="flex-grow:1;min-width:0;border:0;background:transparent;color:{t['t1']};font-family:{SANS};font-size:13px;outline:none">
    <span style="font-family:{MONO};font-size:11px;color:{t['t3']}">⌘K</span>
  </div>
  <div style="flex-grow:1"></div>
  {btn(t, svg('tray', 15) + badge, 'icon', aria=f'Needs you: {tray} items')}
  {btn(t, svg(theme_icon, 15), 'icon', aria=theme_aria)}
  <button aria-label="Account menu" style="width:30px;height:30px;border-radius:999px;border:1px solid {t['b2']};background:{t['inp']};color:{t['t1']};font-family:{SANS};font-size:11px;font-weight:600;cursor:pointer">AU</button>
</div>'''

NAV = [('Home', 'home'), ('Needs you', 'tray', '3'), ('Briefing', 'brief'), ('Runs', 'runs'),
       'Data', ('Catalog', 'catalog'), ('SQL', 'sql'), ('Semantic layer', 'semantic'),
       'Model', ('Ontology', 'ontology'), ('Graph', 'graph'), ('Actions', 'actions'),
       'Operate', ('Agents', 'agents'), ('Automations', 'automations'), ('Monitors', 'monitors'), ('Departures', 'departures'),
       'Govern', ('Spend', 'spend'), ('Security', 'security'), ('Evals', 'evals')]

def navrow(t, name, icon, active=False, badge=None):
    if active:
        st = f"background:{t['navActiveBg']};color:{t['navActiveText']};font-weight:600;{t['navBar']}"
        cur = ' aria-current="page"'
    else:
        st = f"background:transparent;color:{t['t2']};font-weight:400;"
        cur = ''
    b = (f'<span style="min-width:18px;padding:0 5px;border-radius:{t["r"]}px;background:{t["amb1"]};color:{t["amb4"]};font-size:11px;'
         f'font-weight:600;text-align:center;line-height:18px">{badge}</span>') if badge else ''
    return (f'<a href="#{name.lower().replace(" ", "-")}"{cur} style="height:28px;box-sizing:border-box;display:flex;align-items:center;gap:10px;'
            f'padding:0 10px;border-radius:{t["r"]}px;font-size:13px;text-decoration:none;{st}">'
            f'<span style="width:14px;display:inline-flex;color:{t["navActiveText"] if active else t["t3"]}">{svg(icon)}</span>'
            f'<span style="flex-grow:1">{name}</span>{b}</a>')

def sidebar(t, active):
    rows = []
    for item in NAV:
        if isinstance(item, str):
            rows.append(f'<div style="margin:12px 10px 4px;font-size:12px;font-weight:600;color:{t["t3"]}">{item}</div>')
        else:
            name, icon = item[0], item[1]
            badge = item[2] if len(item) > 2 else None
            rows.append(navrow(t, name, icon, active=(name == active), badge=badge))
    ask = (f'<a href="#ask" style="height:32px;margin:0 0 8px;box-sizing:border-box;display:flex;align-items:center;justify-content:center;gap:8px;'
           f'border-radius:{t["r"]}px;background:{t["primary"]};color:{t["onPrimary"]};font-size:13px;font-weight:600;text-decoration:none">'
           f'{svg("ask", 14, 1.8)}Ask a question</a>')
    return f'''<nav aria-label="Primary" style="width:248px;flex-shrink:0;box-sizing:border-box;display:flex;flex-direction:column;gap:2px;background:{t['chrome']};border-right:1px solid {t['b1']};padding:12px 8px 8px">
  {ask}
  {''.join(rows)}
  <div style="flex-grow:1"></div>
  <div style="border-top:1px solid {t['b1']};padding-top:6px;display:flex;flex-direction:column;gap:2px">
    {navrow(t, 'Settings', 'settings')}
    <div style="padding:2px 10px 0;font-size:12px;color:{t['t3']}">v2 · local · 3 connections</div>
  </div>
</nav>'''

def header(t, crumb, title, chip, actions):
    return f'''<div style="height:44px;flex-shrink:0;box-sizing:border-box;display:flex;align-items:center;gap:12px;padding:0 24px;border-bottom:1px solid {t['b1']};background:{t['page']}">
  <div style="display:flex;align-items:baseline;gap:8px"><span style="font-size:13px;color:{t['t3']}">{crumb} /</span><h1 style="margin:0;font-size:15px;font-weight:600;color:{t['t1']}">{title}</h1></div>
  {chip}
  <div style="flex-grow:1"></div>
  {actions}
</div>'''

def tabs(t, items, active, counts=None):
    counts = counts or {}
    out = []
    for it in items:
        on = it == active
        c = counts.get(it)
        cnt = f'<span style="margin-left:6px;font-size:12px;font-weight:600;color:{t["amb4"]}">{c}</span>' if c else ''
        if t['excel']:
            st = (f"background:{t['page']};color:{t['accentText']};font-weight:600;box-shadow:inset 0 -2px 0 {t['accent']};" if on
                  else f"background:transparent;color:{t['t2']};font-weight:400;")
            out.append(f'<button role="tab" aria-selected="{"true" if on else "false"}" style="height:36px;padding:0 16px;border:0;border-right:1px solid {t["b1"]};'
                       f'font-family:{SANS};font-size:13px;cursor:pointer;{st}">{it}{cnt}</button>')
        else:
            st = (f"color:{t['t1']};font-weight:600;box-shadow:inset 0 -2px 0 {t['accent']};" if on
                  else f"color:{t['t2']};font-weight:400;")
            out.append(f'<button role="tab" aria-selected="{"true" if on else "false"}" style="height:36px;padding:0 2px;border:0;background:transparent;'
                       f'font-family:{SANS};font-size:13px;cursor:pointer;{st}">{it}{cnt}</button>')
    if t['excel']:
        return (f'<div role="tablist" style="height:36px;flex-shrink:0;box-sizing:border-box;display:flex;padding:0 24px;background:{t["chrome"]};'
                f'border-bottom:1px solid {t["b1"]}">{"".join(out)}</div>')
    return (f'<div role="tablist" style="height:36px;flex-shrink:0;box-sizing:border-box;display:flex;gap:24px;padding:0 24px;background:{t["page"]};'
            f'border-bottom:1px solid {t["b0"]}">{"".join(out)}</div>')

def toolbar(t, left, right):
    return (f'<div style="height:36px;flex-shrink:0;box-sizing:border-box;display:flex;align-items:center;gap:12px;padding:0 24px;'
            f'border-bottom:1px solid {t["b0"]};background:{t["page"]};font-size:12px;color:{t["t2"]}">{left}<div style="flex-grow:1"></div>{right}</div>')

# ── data surfaces ────────────────────────────────────────────────────────────
def card_style(t, selected=False):
    s = f"text-align:left;padding:12px 14px;border-radius:{t['r']}px;border:1px solid {t['b1']};background:{t['card']};color:{t['t1']};cursor:pointer;"
    if selected:
        if t['excel']:
            s += f"background:{t['sel']};box-shadow:inset 0 0 0 2px {t['accent']};border-color:{t['accent']};"
        else:
            s += f"background:{t['sel']};border-color:{t['accent']};"
    return s

def tile(t, figure, name, meta, selected=False):
    return (f'<button aria-pressed="{"true" if selected else "false"}" style="{card_style(t, selected)}">'
            f'<div style="font-size:22px;font-weight:600;letter-spacing:-0.01em;line-height:1.2;{TAB}">{figure}</div>'
            f'<div style="font-size:13px;color:{t["t2"]};margin-top:4px">{name}</div>'
            f'<div style="font-size:12px;color:{t["t3"]};margin-top:6px;{TAB}">{meta}</div></button>')

def stat(t, name, figure, sub, tone=None):
    fig_col = t[tone] if tone else t['t1']
    return (f'<div style="{card_style(t)}cursor:default">'
            f'<div style="font-size:12px;font-weight:600;color:{t["t2"]}">{name}</div>'
            f'<div style="font-size:24px;font-weight:600;letter-spacing:-0.01em;line-height:1.2;margin-top:6px;color:{fig_col};{TAB}">{figure}</div>'
            f'<div style="font-size:12px;color:{t["t3"]};margin-top:6px">{sub}</div></div>')

def table(t, cols, rows, selected=None, sorted_col=None):
    """cols: [(label, width_css, align)]; rows: list of lists of cell html; selected: row index."""
    gt = ' '.join(c[1] for c in cols)
    excel = t['excel']
    def cell(i, content, is_header=False, last_row=False):
        align = cols[i][2]
        jc = 'flex-end' if align == 'right' else 'flex-start'
        br = f'border-right:1px solid {t["b0"]};' if (excel and i < len(cols) - 1) else ''
        pad = '0 12px' if is_header else '6px 12px'
        return (f'<div style="padding:{pad};min-height:{"32px" if is_header else "34px"};box-sizing:border-box;display:flex;align-items:center;'
                f'justify-content:{jc};gap:6px;{br}min-width:0">{content}</div>')
    hcells = []
    for i, c in enumerate(cols):
        lab = f'<span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{c[0]}</span>'
        if excel:
            lab += f'<span style="margin-left:auto;color:{t["t3"]};display:inline-flex">{svg("chev", 11)}</span>'
        elif sorted_col == i:
            lab += f'<span style="color:{t["t3"]};display:inline-flex">{svg("sortdown", 11)}</span>'
        hcells.append(cell(i, lab, is_header=True))
    head = (f'<div style="display:grid;grid-template-columns:{gt};background:{t["headerBg"]};border-bottom:1px solid {t["b1"]};'
            f'font-size:12px;font-weight:600;color:{t["t2"]}">{"".join(hcells)}</div>')
    body = []
    for ri, r in enumerate(rows):
        sel = ri == selected
        last = ri == len(rows) - 1
        bb = f'border-bottom:1px solid {t["b0"]};' if not last else ''
        if sel:
            st = (f"background:{t['sel']};box-shadow:inset 0 0 0 2px {t['accent']};" if excel
                  else f"background:{t['sel']};box-shadow:inset 2px 0 0 {t['accent']};")
        else:
            st = ''
        cells = ''.join(cell(i, c) for i, c in enumerate(r))
        body.append(f'<div style="display:grid;grid-template-columns:{gt};{bb}{st}font-size:14px;color:{t["t1"]}">{cells}</div>')
    radius = '2px' if excel else f'{t["r"]}px'
    return (f'<div style="border:1px solid {t["b1"]};border-radius:{radius};overflow:hidden;background:{t["page"] if excel else t["card"]}">'
            f'{head}{"".join(body)}</div>')

def bars(t, heights):
    out = []
    for h, k in heights:
        col = {'ok': t['grn3'], 'bad': t['red3'], 'none': t['b2']}[k]
        out.append(f'<span style="width:4px;height:{h}px;background:{col};border-radius:1px"></span>')
    return f'<div aria-label="Runs over the range" style="height:14px;display:flex;gap:2px;align-items:flex-end">{"".join(out)}</div>'

def num(t, s, tone=None):
    col = t[tone] if tone else t['t1']
    return f'<span style="{TAB}color:{col}">{s}</span>'

def muted(t, s):
    return f'<span style="color:{t["t3"]}">{s}</span>'

# ── the annotate tweak ───────────────────────────────────────────────────────
def ann(t, items):
    chips = ''.join(f'<div style="position:absolute;left:{x}px;top:{y}px;padding:2px 7px;border-radius:3px;background:{t["ann"]};color:#1F1F1F;'
                    f'font-family:{MONO};font-size:11px;font-weight:500;white-space:nowrap;box-shadow:0 1px 2px rgba(0,0,0,.35)">{txt}</div>'
                    for x, y, txt in items)
    return f'<sc-if value="{{{{ann}}}}" hint-placeholder-val="{{{{true}}}}">{chips}</sc-if>'

def page(title, t, w, h, body, notes):
    return f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<script src="./support.js"></script>
</head>
<body>
<x-dc>
<helmet>
{FONTS}
<style>
body{{margin:0;background:{t['page']}}}
a{{color:{t['link']}}}a:hover{{color:{t['link']};text-decoration:underline}}
button,input{{font-family:inherit}}
</style>
</helmet>
<div style="position:relative;width:{w}px;height:{h}px;box-sizing:border-box;display:flex;flex-direction:column;background:{t['page']};color:{t['t1']};font-family:{SANS};font-size:14px;line-height:1.5;overflow:hidden">
{body}
{ann(t, notes)}
</div>
</x-dc>
<script type="text/x-dc" data-dc-script data-props='{{"annotate":{{"editor":"boolean","default":true,"section":"Spec"}},"$preview":{{"width":{w},"height":{h}}}}}'>
class Component extends DCLogic {{
  renderVals() {{
    return {{ ann: this.props.annotate ?? true }};
  }}
}}
</script>
</body>
</html>
'''

# ── Briefing ─────────────────────────────────────────────────────────────────
def briefing(t):
    chip = tag(t, 'Grounded and guarded', 'good', dot=True)
    actions = btn(t, 'Regenerate') + btn(t, svg('more', 14), 'icon', aria='More actions')
    findings = [
        [muted(t, 'Key questions'), 'Outerwear &amp; Coats is the top category by total profit, then Jeans and Sweaters.', num(t, '5 categories'), tag(t, 'Verified', 'good')],
        [muted(t, 'Key questions'), 'Monthly orders rose from 6 in January 2019 to 291 in August 2020, about 15 more a month.', num(t, '+15 / month'), tag(t, 'Verified', 'good')],
        [muted(t, 'Catalog'), 'Department cost is only Men and Women, so the two account for all inventory cost.', num(t, '7,490,112.40 · 6,501,930.15'), tag(t, 'Re-check due', 'warn')],
        [muted(t, 'Key questions'), 'Email drove the most unique user activity, ahead of Adwords and YouTube.', num(t, '52,142 users'), tag(t, 'Verified', 'good')],
    ]
    body_main = f'''
<div style="flex-grow:1;min-width:0;padding:24px 24px 0;overflow:hidden">
  <div style="max-width:760px;display:flex;flex-direction:column;gap:22px">
    <div style="font-size:12px;color:{t['t3']}">Intelligence briefing · theLook</div>
    <div>
      {label(t, 'Verdict', 'margin-bottom:8px')}
      <h2 style="margin:0 0 8px;font-size:22px;line-height:1.25;font-weight:600;letter-spacing:-0.01em;color:{t['t1']}">Category visibility gap masks revenue risk</h2>
      <p style="margin:0;font-size:14px;line-height:1.6;color:{t['t2']}">Overall return rate is {num(t, '10.03%')}, roughly one in ten order items comes back. Suits return most at {num(t, '14.59%')}, ahead of Outerwear &amp; Coats and Swim, and sales volume is visible only as one aggregate, so the categories that carry the risk cannot yet be watched one by one.</p>
      <div style="display:flex;gap:8px;margin-top:12px;align-items:center">
        {btn(t, 'Investigate', 'primary')}{btn(t, 'Monitor')}{btn(t, 'Pin')}
      </div>
    </div>
    <div>
      {label(t, 'Numbers that moved', 'margin-bottom:8px')}
      <div style="display:grid;grid-template-columns:repeat(4, minmax(0, 1fr));gap:12px">
        {tile(t, '10.03%', 'Return rate, all items', 'Commerce · 61,270 of 610,700')}
        {tile(t, '$1.82M', 'Inventory cost, Jeans', 'Catalog · 1,820,497.55 USD', selected=True)}
        {tile(t, '$3.56M', 'Retail value, Outerwear &amp; Coats', 'Commerce · 3,561,748.63 USD')}
        {tile(t, '14.59%', 'Return rate, Suits', 'Key questions · 2,101 of 14,400')}
      </div>
    </div>
    <div>
      <div style="display:flex;align-items:baseline;gap:12px;margin-bottom:8px">{label(t, 'Findings')}<span style="font-size:12px;color:{t['t3']}">6 of 13 · ranked by novelty</span><div style="flex-grow:1"></div><span style="font-size:12px;color:{t['t2']}">Key questions 5 · Catalog 3 · Commerce 3 · Customer 2</span></div>
      {table(t, [('Domain', '116px', 'left'), ('Finding', 'minmax(0, 1fr)', 'left'), ('Figure', '168px', 'right'), ('Checked', '116px', 'left')], findings, sorted_col=None)}
    </div>
  </div>
</div>'''
    sql = 'SELECT product_category,\n       SUM(cost) AS inventory_cost\nFROM inventory_items\nGROUP BY 1 ORDER BY 2 DESC LIMIT 3'
    inspector = f'''
<aside aria-label="Selected number" style="width:400px;flex-shrink:0;box-sizing:border-box;display:flex;flex-direction:column;border-left:1px solid {t['b1']};background:{t['card']}">
  <div style="height:44px;flex-shrink:0;box-sizing:border-box;display:flex;align-items:center;gap:8px;padding:0 16px;border-bottom:1px solid {t['b0']}">
    <span style="font-size:14px;font-weight:600">Inventory cost, Jeans</span>
    <div style="flex-grow:1"></div>
    {btn(t, svg('close', 14), 'icon', aria='Close the inspector')}
  </div>
  <div style="padding:16px;display:flex;flex-direction:column;gap:16px;overflow:hidden">
    <div style="display:flex;align-items:baseline;gap:10px"><span style="font-size:28px;font-weight:600;letter-spacing:-0.02em;line-height:1.1;{TAB}">1,820,497.55</span><span style="font-size:12px;color:{t['t2']}">USD · org setting</span></div>
    <p style="margin:0;font-size:14px;line-height:1.6;color:{t['t1']}">Inventory cost is concentrated in Jeans, Outerwear &amp; Coats and Sweaters, the three highest-cost product categories.</p>
    <div>
      {label(t, 'Why this number', 'margin-bottom:6px')}
      <pre style="margin:0;padding:10px 12px;border-radius:{t['r']}px;background:{t['code']};border:1px solid {t['b1']};font-family:{MONO};font-size:12px;line-height:1.6;color:{t['t2']};white-space:pre-wrap;overflow:hidden">{sql}</pre>
      <div style="display:flex;gap:6px;margin-top:8px;flex-wrap:wrap">{tag(t, 'Grain checked', 'good')}{tag(t, 'Join coverage', 'good')}{tag(t, 'Re-check stable', 'good')}{tag(t, '488,476 rows read')}</div>
    </div>
    <div>
      {label(t, 'Is this right?', 'margin-bottom:6px')}
      <div style="display:flex;gap:8px">{btn(t, 'Yes')}{btn(t, 'Correct it…')}{btn(t, 'No')}</div>
      <div style="font-size:12px;color:{t['t3']};margin-top:6px">Your answer is kept with the number and teaches the next one.</div>
    </div>
    <div style="display:flex;gap:16px;font-size:13px"><a href="#promote">Promote to Org</a><a href="#watch">Watch it</a><a href="#jeans">Open Jeans</a></div>
  </div>
</aside>'''
    ctx_left = (f'<span style="display:inline-flex;align-items:center;gap:8px;font-size:13px;color:{t["t2"]}">{dot(t, t["amb3"])}Explorer stopped short, earlier findings kept'
                f'<a href="#explore" style="font-size:13px;margin-left:2px">Run again</a></span>'
                f'<div style="width:1px;height:16px;background:{t["b2"]}"></div>'
                f'<span style="font-size:12px;font-weight:600;color:{t["t3"]}">Period</span>{seg(t, ["Standing", "Day", "Week", "Month", "Year"], "Standing")}'
                f'{btn(t, "Schedule…", "ghost")}')
    ctx_right = f'<span style="font-size:12px;color:{t["t3"]}">written 1 min ago · 4 domains · 13 findings</span>'
    content = f'''
{topbar(t, 3)}
<div style="flex-grow:1;display:flex;min-height:0">
  {sidebar(t, 'Briefing')}
  <div style="flex-grow:1;display:flex;flex-direction:column;min-width:0">
    {header(t, 'Intelligence', 'Briefing', chip, actions)}
    {toolbar(t, ctx_left, ctx_right)}
    {tabs(t, ['Briefing', 'Profile', 'Evidence', 'Memory', 'Org', 'Brain map'], 'Briefing')}
    <div style="flex-grow:1;display:flex;min-height:0">{body_main}{inspector}</div>
  </div>
</div>'''
    if t['excel']:
        notes = [
            (300, 56, 'chrome is Excel grey #F3F3F3 · the page is white · text #1F1F1F'),
            (300, 100, 'context bar: explorer status · period · schedule — no definition bar, no status bar (decided 2026-09-25)'),
            (760, 136, 'layer tabs drawn as sheet tabs: white active, green underline'),
            (300, 400, 'selected tile: Excel\'s thick green cell border, green tint · figures in Inter tabular'),
            (300, 580, 'findings as a grid: gridlines both ways, filter chevrons, Good/Neutral cell fills'),
            (1060, 300, 'the inspector stays: why this number, and the grading row'),
        ]
    else:
        notes = [
            (300, 56, 'page #11171C · chrome and cards #1F272D · borders #3F5162 · text #E8ECF0'),
            (300, 100, 'context bar: explorer status · period · schedule — no definition bar, no status bar (decided 2026-09-25)'),
            (760, 136, 'Databricks tabs: text with a 2 px blue underline'),
            (300, 400, 'selected tile: blue border, navy tint · figures in Inter tabular, not mono'),
            (300, 580, 'findings: hairline rows, pills for the check state'),
            (1060, 300, 'the inspector stays: why this number, and the grading row'),
        ]
    return page('Briefing — ' + ('light, after Excel' if t['excel'] else 'dark, after Databricks'), t, 1440, 900, content, notes)

# ── Agent Ops ────────────────────────────────────────────────────────────────
def agentops(t):
    chip = tag(t, '4 agents · 1 runner', 'neutral')
    actions = btn(t, svg('plus', 14, 1.8) + 'Create agent', 'primary')
    left = (f'<span style="font-size:12px;font-weight:600;color:{t["t3"]}">Range</span>{seg(t, ["1h", "6h", "24h", "7d", "30d"], "24h", width=40)}'
            f'{btn(t, "Status: all " + svg("chev", 12))}{btn(t, "Connection: all " + svg("chev", 12))}'
            f'<div style="width:220px;height:28px;box-sizing:border-box;display:flex;align-items:center;gap:8px;padding:0 10px;border:1px solid {t["b2"]};border-radius:{t["r"]}px;background:{t["inp"]};color:{t["t3"]}">'
            f'{svg("filter", 13)}<input aria-label="Filter agents" placeholder="Filter agents" style="flex-grow:1;min-width:0;border:0;background:transparent;color:{t["t1"]};font-size:13px;outline:none"></div>')
    right = f'<span style="font-size:12px;color:{t["t3"]}">agents only · 5,749 background ticks excluded</span>'
    def agent(name, blurb):
        slug = name.lower().replace(' ', '-')
        return (f'<a href="#agent-{slug}" style="color:{t["link"]};font-weight:500;text-decoration:none;white-space:nowrap">{name}</a>'
                f'<span style="color:{t["t3"]};margin-left:6px">· {blurb}</span>')
    rows = [
        [agent('Explorer', 'data explorer'), tag(t, 'Idle'), num(t, '1'), num(t, '0'), num(t, '5 h ago'), num(t, '96.1K'), bars(t, [(4, 'none'), (12, 'ok'), (3, 'none'), (6, 'none'), (3, 'none'), (8, 'none'), (3, 'none'), (5, 'none')])],
        [agent('Analyst', 'deep analysis'), tag(t, 'Idle'), num(t, '1'), num(t, '0'), num(t, '15 h ago'), num(t, '59.4K'), bars(t, [(10, 'ok'), (3, 'none'), (3, 'none'), (3, 'none'), (5, 'none'), (3, 'none'), (3, 'none'), (3, 'none')])],
        [agent('Responder', 'quick answers'), tag(t, 'Idle'), muted(t, '—'), muted(t, '—'), muted(t, '—'), muted(t, '—'), muted(t, 'not metered as jobs')],
        [agent('The Look Analyst', 'custom'), tag(t, 'Held', 'warn'), num(t, '2'), num(t, '2', 'red4'), num(t, '14 h ago'), num(t, '21.8K'), bars(t, [(3, 'none'), (12, 'bad'), (11, 'bad'), (3, 'none'), (3, 'none'), (3, 'none'), (3, 'none'), (3, 'none')])],
    ]
    runner_rows = [
        [agent('Watcher', 'metric watches'), tag(t, 'Running', 'good', dot=True), num(t, '5,749'), num(t, '0'), num(t, '2 min ago'), muted(t, 'not metered'), bars(t, [(8, 'ok')] * 8)],
    ]
    cols = [('Agent', 'minmax(0, 1fr)', 'left'), ('Status', '120px', 'left'), ('Runs', '80px', 'right'), ('Failures', '96px', 'right'),
            ('Last run', '112px', 'right'), ('Tokens', '96px', 'right'), ('Activity', '160px', 'left')]
    body_main = f'''
<div style="flex-grow:1;min-width:0;padding:24px 24px 0;display:flex;flex-direction:column;gap:20px;overflow:hidden">
  <div style="display:grid;grid-template-columns:repeat(4, minmax(0, 1fr));gap:12px">
    {stat(t, 'Runs', '4', 'finished in the last 24 h')}
    {stat(t, 'Failures', '2', '50% of finished runs · both The Look Analyst', 'red4')}
    {stat(t, 'Duration p50 · p95', '10m 07s · 14m 52s', 'typical · slow')}
    {stat(t, 'Tokens', '177.3K', 'all finished runs metered · cost unpriced')}
  </div>
  <div>
    <div style="display:flex;align-items:baseline;gap:12px;margin-bottom:8px">{label(t, 'Agents')}<span style="font-size:12px;color:{t['t3']}">3 built-in · 1 custom</span></div>
    {table(t, cols, rows, sorted_col=5)}
  </div>
  <div>
    <div style="display:flex;align-items:baseline;gap:12px;margin-bottom:8px">{label(t, 'Runners')}<span style="font-size:12px;color:{t['t3']}">background ticks, never summed into the cards above</span></div>
    {table(t, cols, runner_rows)}
  </div>
</div>'''
    content = f'''
{topbar(t, 1)}
<div style="flex-grow:1;display:flex;min-height:0">
  {sidebar(t, 'Agents')}
  <div style="flex-grow:1;display:flex;flex-direction:column;min-width:0">
    {header(t, 'Operate', 'Agents', chip, actions)}
    {tabs(t, ['Overview', 'Roster', 'Attention', 'Activity', 'Automations', 'Hub', 'Departures'], 'Overview', {'Attention': 1})}
    {toolbar(t, left, right)}
    <div style="flex-grow:1;display:flex;min-height:0">{body_main}</div>
  </div>
</div>'''
    if t['excel']:
        notes = [
            (300, 100, 'sheet tabs, then the toolbar under them: Range · Status · Connection · Filter — one row, never beside the tabs'),
            (300, 290, 'stat cards: white boxes, 24 px figures in tabular Inter, the adverse one in Excel\'s Bad red · "cost unpriced" stays on its card'),
            (300, 470, 'agent names are links: the click opens that agent\'s own page — nothing opens inside the overview (decided 2026-09-25)'),
            (300, 640, 'Held and Failures as Neutral / Bad cell fills · filter chevrons in the header row · no status bar, no definition bar'),
        ]
    else:
        notes = [
            (300, 100, 'Databricks tabs, then the toolbar under them: Range · Status · Connection · Filter — one row, never beside the tabs'),
            (300, 290, 'stat cards on #1F272D with #2F3C47 borders, figures 24 px in tabular Inter · "cost unpriced" stays on its card'),
            (300, 470, 'agent names are links: the click opens that agent\'s own page — nothing opens inside the overview (decided 2026-09-25)'),
            (300, 640, 'Held and Running as Databricks pills · no status bar, no definition bar (decided 2026-09-25)'),
        ]
    return page('Agent Ops — ' + ('light, after Excel' if t['excel'] else 'dark, after Databricks'), t, 1440, 900, content, notes)

# ── the token board ──────────────────────────────────────────────────────────
def swatch(t, hexv, name, w=118, h=56, border=None):
    bd = border or t['b1']
    return (f'<div style="width:{w}px"><div style="height:{h}px;border-radius:{t["r"]}px;background:{hexv};border:1px solid {bd}"></div>'
            f'<div style="font-size:12px;color:{t["t1"]};margin-top:6px">{name}</div><div style="font-family:{MONO};font-size:11px;color:{t["t3"]}">{hexv}</div></div>')

def line_swatch(t, hexv, name):
    return (f'<div style="width:118px"><div style="height:56px;display:flex;align-items:center"><div style="width:100%;height:2px;background:{hexv}"></div></div>'
            f'<div style="font-size:12px;color:{t["t1"]};margin-top:6px">{name}</div><div style="font-family:{MONO};font-size:11px;color:{t["t3"]}">{hexv}</div></div>')

def text_row(t, key, sample, note):
    return (f'<div style="display:grid;grid-template-columns:minmax(0, 1fr) 90px 80px;gap:12px;align-items:baseline;padding:6px 0;border-bottom:1px solid {t["b0"]}">'
            f'<span style="font-size:14px;color:{t[key]}">{sample} <span style="font-size:12px;color:{t["t3"]}">{note}</span></span>'
            f'<span style="font-family:{MONO};font-size:11px;color:{t["t3"]}">{t[key]}</span>'
            f'<span style="font-family:{MONO};font-size:11px;color:{t["t3"]};text-align:right;{TAB}">{ratio(t[key], t["page"])} on page</span></div>')

def intent_row(t, name, k, chip_text, meaning):
    a, b, c, d = t[k + '1'], t[k + '2'], t[k + '3'], t[k + '4']
    kind = {'blue': 'info', 'grn': 'good', 'amb': 'warn', 'red': 'bad', 'vio': 'deep'}[k]
    return (f'<div style="display:grid;grid-template-columns:150px 130px 20px minmax(0, 1fr) 210px;gap:12px;align-items:center;padding:6px 0;border-bottom:1px solid {t["b0"]}">'
            f'<span style="font-size:13px;color:{t["t1"]}">{name} <span style="font-size:12px;color:{t["t3"]}">{meaning}</span></span>'
            f'<span>{tag(t, chip_text, kind)}</span>'
            f'{dot(t, c).replace("width:7px;height:7px", "width:12px;height:12px")}'
            f'<span style="font-size:14px;color:{d}">A figure in this colour {muted(t, ratio(d, a) + " on its tint")}</span>'
            f'<span style="font-family:{MONO};font-size:11px;color:{t["t3"]}">{a} · {b} · {c} · {d}</span></div>')

def panel(t, title, sub, origin):
    sample_rows = [
        ['Suits', num(t, '14.59%', 'red4' if not t['excel'] else None) if False else num(t, '14.59%'), num(t, '2,101'), num(t, '14,400')],
        ['Outerwear &amp; Coats', num(t, '12.87%'), num(t, '3,912'), num(t, '30,393')],
        ['Swim', num(t, '12.30%'), num(t, '1,208'), num(t, '9,821')],
    ]
    tbl = table(t, [('Category', 'minmax(0, 1fr)', 'left'), ('Return rate', '110px', 'right'), ('Returned', '100px', 'right'), ('Items', '100px', 'right')], sample_rows, selected=0, sorted_col=1)
    type_rows = [
        (22, 600, 'Verdict and the selected figure', '22 · semibold'),
        (18, 600, 'Section title, inspector figure', '18 · semibold'),
        (15, 600, 'Page title', '15 · semibold'),
        (14, 400, 'Body: findings, prose, table cells, tile labels', '14 · regular · the reading size'),
        (13, 500, 'Chrome: nav, tabs, buttons, inputs', '13 · medium'),
        (12, 400, 'Meta and captions: never lighter than t3', '12 · regular'),
        (11, 500, 'Ids and shortcuts in mono, never a sentence', '11 · mono'),
    ]
    type_html = ''.join(f'<div style="display:flex;align-items:baseline;gap:12px;padding:5px 0;border-bottom:1px solid {t["b0"]}">'
                        f'<span style="font-size:{s}px;font-weight:{w};color:{t["t1"]};{"font-family:" + MONO + ";" if s == 11 else ""}flex-grow:1;line-height:1.3">{txt}</span>'
                        f'<span style="font-family:{MONO};font-size:11px;color:{t["t3"]};white-space:nowrap">{note}</span></div>' for s, w, txt, note in type_rows)
    return f'''<div style="width:680px;box-sizing:border-box;padding:24px 28px 28px;border-radius:{t['r'] + 2}px;border:1px solid {t['b1']};background:{t['page']};color:{t['t1']};font-family:{SANS};font-size:14px;line-height:1.5;display:flex;flex-direction:column;gap:20px">
  <div>
    <div style="font-size:22px;font-weight:600;letter-spacing:-0.01em;line-height:1.2">{title}</div>
    <div style="font-size:13px;color:{t['t2']};margin-top:6px;line-height:1.5">{sub}</div>
    <div style="font-size:12px;color:{t['t3']};margin-top:4px">{origin}</div>
  </div>
  <div>
    {label(t, 'Surfaces', 'margin-bottom:8px')}
    <div style="display:flex;gap:12px">{swatch(t, t['page'], 'Page and grid')}{swatch(t, t['chrome'], 'Chrome: bars, rail, headers')}{swatch(t, t['hover'], 'Hover')}{swatch(t, t['sel'], 'Selected', border=t['accent'])}{swatch(t, t['code'], 'Code well')}</div>
  </div>
  <div>
    {label(t, 'Lines', 'margin-bottom:8px')}
    <div style="display:flex;gap:12px">{line_swatch(t, t['b0'], 'Row rule, gridline')}{line_swatch(t, t['b1'], 'Panel edge')}{line_swatch(t, t['b2'], 'Control border')}{line_swatch(t, t['b3'], 'Strong')}{line_swatch(t, t['accent'], 'Selection edge, active tab')}</div>
  </div>
  <div>
    {label(t, 'Text', 'margin-bottom:2px')}
    {text_row(t, 't1', 'Suits return most at 14.59%', 'body, figures, titles')}
    {text_row(t, 't2', 'Ahead of Outerwear &amp; Coats and Swim', 'secondary, tile labels, status bar')}
    {text_row(t, 't3', 'written 1 min ago · 13 findings', 'captions and meta, the floor')}
    <div style="display:grid;grid-template-columns:minmax(0, 1fr) 90px 80px;gap:12px;align-items:baseline;padding:6px 0"><span style="font-size:13px;color:{t['t4']}">Placeholder, ticks, rules <span style="font-size:12px;color:{t['t3']}">never text</span></span><span style="font-family:{MONO};font-size:11px;color:{t['t3']}">{t['t4']}</span><span></span></div>
  </div>
  <div>
    {label(t, 'Intent — tint · border · colour · text', 'margin-bottom:2px')}
    {intent_row(t, 'Blue', 'blue', 'Live', 'interactive, information')}
    {intent_row(t, 'Green', 'grn', 'Verified', 'guard passed, healthy')}
    {intent_row(t, 'Amber', 'amb', 'Held', 'waiting on a human')}
    {intent_row(t, 'Red', 'red', 'Failed', 'adverse figure, failed run')}
    {intent_row(t, 'Violet', 'vio', 'Deep', 'deep analysis')}
  </div>
  <div>
    {label(t, 'Controls', 'margin-bottom:8px')}
    <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
      {btn(t, 'Investigate', 'primary')}{btn(t, 'Monitor')}{btn(t, 'Cancel', 'ghost')}
      <div style="width:200px;height:28px;box-sizing:border-box;display:flex;align-items:center;padding:0 10px;border:1px solid {t['b2']};border-radius:{t['r']}px;background:{t['inp']};color:{t['t3']}"><input aria-label="Filter" placeholder="Filter…" style="flex-grow:1;min-width:0;border:0;background:transparent;color:{t['t1']};font-size:13px;outline:none"></div>
      {seg(t, ['Standing', 'Day', 'Week'], 'Standing')}
      <a href="#link" style="font-size:13px">A link</a>
    </div>
    <div style="margin-top:12px;display:inline-flex;border:1px solid {t['b1']};border-radius:{t['r']}px;overflow:hidden">{tabs(t, ['Briefing', 'Profile', 'Evidence'], 'Briefing').replace('padding:0 24px', 'padding:0 12px').replace('height:36px;flex-shrink:0;box-sizing:border-box;display:flex;', 'height:36px;box-sizing:border-box;display:flex;')}</div>
  </div>
  <div>
    {label(t, 'A table', 'margin-bottom:8px')}
    {tbl}
  </div>
  <div>
    {label(t, 'Type', 'margin-bottom:2px')}
    {type_html}
  </div>
</div>'''

def tokens_board():
    d = panel(DARK, 'Dark — after Databricks',
              'Cool navy greys, not warm charcoal. Borders you can see. Blue is the only thing that means "you can click this". Cards and rails sit one step lighter than the page.',
              'Greys and hues follow Du Bois, Databricks\' design system: 900 → 500 greys, blue 400/500/600, green 400/500, yellow 400/500, red 400/500.')
    l = panel(LIGHT, 'Light — after Excel',
              'A white grid, grey chrome, near-black text. Gridlines both ways. Excel green is the selection and the primary; blue stays the link. Good, Bad and Neutral are Excel\'s own cell fills.',
              'Greys follow Fluent 2 neutrals, the accent is Excel\'s #107C41, the fills are Excel\'s Good #C6EFCE/#006100 · Bad #FFC7CE/#9C0006 · Neutral #FFEB9C/#9C5700.')
    t = DARK
    content = f'''
<div style="display:flex;gap:16px;padding:32px;align-items:flex-start">{d}{l}</div>'''
    html = f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Tokens — two skins</title>
<script src="./support.js"></script>
</head>
<body>
<x-dc>
<helmet>
{FONTS}
<style>
body{{margin:0;background:#0B0F13}}
a{{color:{t['link']}}}a:hover{{color:{t['link']};text-decoration:underline}}
button,input{{font-family:inherit}}
</style>
</helmet>
<div style="position:relative;width:1440px;height:1250px;box-sizing:border-box;background:#0B0F13;color:{t['t1']};font-family:{SANS};font-size:14px;line-height:1.5;overflow:hidden">
{content}
</div>
</x-dc>
<script type="text/x-dc" data-dc-script data-props='{{"$preview":{{"width":1440,"height":1250}}}}'>
class Component extends DCLogic {{
  renderVals() {{
    return {{}};
  }}
}}
</script>
</body>
</html>
'''
    return html

# ── validation of my own markup (tag balance, quoted attrs) ─────────────────
VOID = {'meta', 'link', 'input', 'br', 'img', 'hr', 'path', 'circle', 'ellipse', 'rect', 'line', 'polyline', 'polygon'}
class Checker(HTMLParser):
    def __init__(self):
        super().__init__(); self.stack = []; self.errors = []
    def handle_starttag(self, tag, attrs):
        if tag in VOID: return
        self.stack.append((tag, self.getpos()))
    def handle_endtag(self, tag):
        if tag in VOID: return
        if not self.stack or self.stack[-1][0] != tag:
            self.errors.append(f'mismatch </{tag}> at {self.getpos()} (open: {self.stack[-3:]})')
            while self.stack and self.stack[-1][0] != tag: self.stack.pop()
            if self.stack: self.stack.pop()
        else:
            self.stack.pop()

def check(name, html):
    c = Checker(); c.feed(html)
    if c.stack: c.errors.append(f'unclosed: {c.stack[-5:]}')
    if '&' in html.replace('&amp;', '').replace('&#', ''):
        c.errors.append('raw ampersand')
    if c.errors:
        print('!!', name, c.errors)
    else:
        print('ok', name, len(html), 'bytes')

# ── write ────────────────────────────────────────────────────────────────────
files = {
    'Main.dc.html': tokens_board(),
    'Briefing-Dark.dc.html': briefing(DARK),
    'Briefing-Light.dc.html': briefing(LIGHT),
    'AgentOps-Dark.dc.html': agentops(DARK),
    'AgentOps-Light.dc.html': agentops(LIGHT),
}
for name, html in files.items():
    check(name, html)
    with open(os.path.join(OUT, name), 'w') as f:
        f.write(html)

now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')
BOARDS = {
    'Main.dc.html': {'x': 0, 'y': 0, 'w': 1440, 'h': 1250, 'title': '1 · Tokens — dark after Databricks, light after Excel'},
    'Briefing-Dark.dc.html': {'x': 1520, 'y': 0, 'w': 1440, 'h': 900, 'title': '2 · Briefing — dark'},
    'Briefing-Light.dc.html': {'x': 1520, 'y': 1020, 'w': 1440, 'h': 900, 'title': '3 · Briefing — light'},
    'AgentOps-Dark.dc.html': {'x': 3040, 'y': 0, 'w': 1440, 'h': 900, 'title': '4 · Agent Ops overview — dark'},
    'AgentOps-Light.dc.html': {'x': 3040, 'y': 1020, 'w': 1440, 'h': 900, 'title': '5 · Agent Ops overview — light'},
}
NOTES = {
    'title': {'x': 0, 'y': -300, 'text': 'Aughor — two skins, one layout: Databricks dark · Excel light (mockup, 2026-09-25)', 'kind': 'title1', 'maxW': 4480},
    'shared': {'x': 0, 'y': 1370, 'w': 700, 'fill': 'blue',
               'text': 'One layout, two skins. Every screen is the same region stack in both themes — topbar 48 · rail 248 · header 44 · context bar or toolbar 36 · layer tabs 36 · body · inspector 400 on the Briefing — and the two files differ only by their token set plus four skin rules: gridlines vs hairlines, sheet tabs vs underlined tabs, cell fills vs pills, a green outline vs a blue edge for the selection. Rows are 34 px, controls 28 px, body text 14 px.'},
    'new': {'x': 760, 'y': 1370, 'w': 680, 'fill': 'green',
            'text': 'Decided 2026-09-25: body text 14 px · figures in Inter with tabular numerals, mono only for SQL and ids · light keeps Excel green for its own state (selection, active tab, the primary) and blue for links; dark stays blue · NO definition bar · NO status bar · sentence-case 12 px labels · light chrome is Excel grey #F3F3F3. On Agent Ops the click on an agent opens that agent\'s own page; nothing opens inside the overview.'},
    'calls': {'x': 4560, 'y': 0, 'w': 520, 'fill': 'orange',
              'text': 'Next: wave UI-6 of the study writes these tokens into tokens-v2.css and INSTRUMENT.md and moves the body size to 14 px; §4.5 and UI-6\'s receipt move with it. Not started — the token files are dirty in another session\'s branch, so the lift waits for that to land.'},
    'kept': {'x': 4560, 'y': 560, 'w': 520, 'fill': 'gray',
             'text': 'Kept from earlier decisions: verdict-first Briefing, no numbered gutters (Excel\'s row numbers are NOT adopted), 28 px rail rows and a collapsible rail, press scale on the primary only, the chart palette and its CVD order untouched (lint:palette), no LLM-judge evals, no merging of run planes.'},
}
# Start from the index as it is on the canvas (the viewer edits live), changing only what is mine.
base_path = os.path.join(ROOT, 'canvas.read.json')
if os.path.exists(base_path):
    index = json.load(open(base_path))
    for name, frame in BOARDS.items():
        entry = index['boards'].get(name, {})
        entry.update({k: v for k, v in frame.items() if k not in entry})  # keep the viewer's frame if they moved it
        entry['title'] = frame['title']
        index['boards'][name] = entry
    for name in BOARDS:
        if name not in index['order']:
            index['order'].append(name)
    index.setdefault('notes', {})
    for nid, note in NOTES.items():
        existing = index['notes'].get(nid, {})
        existing.update({k: v for k, v in note.items() if k not in existing or k == 'text'})
        index['notes'][nid] = existing
else:
    index = {
        'v': 3, 'createdOnFiles': {'v': 1, 'at': now}, 'title': 'Aughor Two Skins', 'launch': {'view': 'canvas'}, 'pages': [],
        'boards': BOARDS, 'order': list(BOARDS), 'notes': NOTES, 'designSystems': [],
    }
with open(os.path.join(OUT, 'canvas.json'), 'w') as f:
    json.dump(index, f, indent=2)

# ── contrast report ──────────────────────────────────────────────────────────
print()
for t in (DARK, LIGHT):
    print(t['name'])
    pairs = [('t1/page', 't1', 'page'), ('t2/page', 't2', 'page'), ('t3/page', 't3', 'page'), ('t1/chrome', 't1', 'chrome'),
             ('t2/chrome', 't2', 'chrome'), ('t3/chrome', 't3', 'chrome'), ('link/page', 'link', 'page'), ('link/chrome', 'link', 'chrome'),
             ('onPrimary/primary', 'onPrimary', 'primary'), ('accentText/sel', 'accentText', 'sel'), ('grn4/grn1', 'grn4', 'grn1'),
             ('amb4/amb1', 'amb4', 'amb1'), ('red4/red1', 'red4', 'red1'), ('blue4/blue1', 'blue4', 'blue1'), ('vio4/vio1', 'vio4', 'vio1'),
             ('red4/page', 'red4', 'page'), ('amb4/page', 'amb4', 'page'), ('grn4/page', 'grn4', 'page'), ('t4/page', 't4', 'page'),
             ('segOnText/segOn', 'segOnText', 'segOn'), ('navActiveText/navActiveBg', 'navActiveText', 'navActiveBg'), ('b0/page', 'b0', 'page'), ('b2/page', 'b2', 'page')]
    for name, a, b in pairs:
        r = cr(t[a], t[b])
        flag = '' if r >= 4.5 or a in ('t4', 'b0', 'b2') else '   <-- under 4.5'
        print(f'  {name:26s} {r:5.2f}{flag}')
