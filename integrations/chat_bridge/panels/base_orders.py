# -*- coding: utf-8 -*-
# Panel BaseLinker (Dashboard App w rozmowie): podglad zamowien klienta po e-mailu/telefonie.
import time
import json
import re
import requests
from datetime import datetime
from flask import Blueprint, request, current_app, jsonify
from config import BASELINKER_TOKEN, BASE_PANEL_TOKEN, BL_API
from core.log import log
from core.db import meta_get, meta_set

bp = Blueprint("base_orders", __name__)

# ---------- BaseLinker (panel zamowien) ----------
_BL_SOURCE = {"shop": "Sklep", "allegro": "Allegro", "olx": "OLX", "amazon": "Amazon",
              "ebay": "eBay", "personal": "Ręczne", "order_return": "Zwrot", "erli": "Erli"}


def bl_request(method, params=None):
    if not BASELINKER_TOKEN:
        raise RuntimeError("brak BASELINKER_TOKEN")
    r = requests.post(BL_API, headers={"X-BLToken": BASELINKER_TOKEN},
                      data={"method": method, "parameters": json.dumps(params or {})}, timeout=30)
    r.raise_for_status()
    d = r.json()
    if d.get("status") != "SUCCESS":
        raise RuntimeError("BL %s: %s" % (method, d.get("error_message") or d.get("error_code") or "blad"))
    return d


def bl_status_map():
    cached, ts = meta_get("bl_status_map"), meta_get("bl_status_map_ts")
    now = time.time()
    if cached and ts and now - float(ts) < 3600:
        return json.loads(cached)
    try:
        d = bl_request("getOrderStatusList")
        m = {str(s.get("id")): {"name": s.get("name"), "color": s.get("color")} for s in d.get("statuses", [])}
        meta_set("bl_status_map", json.dumps(m)); meta_set("bl_status_map_ts", now)
        return m
    except Exception as e:
        log("bl_status_map fail:", repr(e))
        return json.loads(cached) if cached else {}


def bl_source_label(code):
    if not code:
        return "—"
    return _BL_SOURCE.get(str(code).lower(), str(code).capitalize())


def _bl_date(ts):
    try:
        return datetime.utcfromtimestamp(int(ts)).strftime("%Y-%m-%d") if ts else ""
    except Exception:
        return ""


def _bl_total_f(o):
    try:
        tot = sum(float(p.get("price_brutto") or 0) * float(p.get("quantity") or 0) for p in (o.get("products") or []))
        tot += float(o.get("delivery_price") or 0)
        return tot
    except Exception:
        return 0.0


def _bl_total(o):
    return "%.2f" % _bl_total_f(o)


def _bl_addr(o, prefix):
    line2 = " ".join(x for x in [o.get(prefix + "_postcode"), o.get(prefix + "_city")] if x)
    parts = [o.get(prefix + "_address"), line2, o.get(prefix + "_country")]
    return ", ".join(p for p in parts if p)


def _bl_delivery_addr(o):
    point = o.get("delivery_point_name")
    if point:
        det = " ".join(x for x in [o.get("delivery_point_postcode"), o.get("delivery_point_city")] if x)
        return "Punkt/paczkomat: " + ", ".join(x for x in [point, o.get("delivery_point_address"), det] if x)
    return _bl_addr(o, "delivery")


def get_orders_by_contact(email, phone):
    orders = {}
    if email:
        try:
            d = bl_request("getOrders", {"filter_email": email, "get_unconfirmed_orders": True})
            for o in d.get("orders", []):
                orders[o["order_id"]] = o
        except Exception as e:
            log("BL getOrders email fail:", repr(e))
    # telefon: tylko gdy brak trafienia po e-mailu (oszczedzamy limit) — okno 90 dni, max 10 stron
    if phone and not orders:
        digits = re.sub(r"\D", "", phone)
        if len(digits) >= 9:
            last9 = digits[-9:]
            since = int(time.time()) - 90 * 86400
            last_id = 0
            try:
                for _ in range(10):
                    params = {"date_from": since, "get_unconfirmed_orders": True}
                    if last_id:
                        params["id_from"] = last_id + 1
                    batch = bl_request("getOrders", params).get("orders", [])
                    if not batch:
                        break
                    for o in batch:
                        ph = re.sub(r"\D", "", o.get("phone") or "")
                        if ph and ph[-9:] == last9:
                            orders[o["order_id"]] = o
                    last_id = batch[-1]["order_id"]
                    if len(batch) < 100:
                        break
            except Exception as e:
                log("BL getOrders phone fail:", repr(e))
    return sorted(orders.values(), key=lambda o: int(o.get("date_add") or 0), reverse=True)


@bp.get("/base/api/orders")
def base_api_orders():
    if BASE_PANEL_TOKEN and request.args.get("token") != BASE_PANEL_TOKEN:
        return jsonify(ok=False, error="unauthorized"), 401
    email = (request.args.get("email") or "").strip()
    phone = (request.args.get("phone") or "").strip()
    if not email and not phone:
        return jsonify(ok=True, orders=[])
    try:
        orders = get_orders_by_contact(email, phone)
    except Exception as e:
        log("base orders ERROR:", repr(e))
        return jsonify(ok=False, error="bl_error"), 200
    smap = bl_status_map()
    rows = []
    for o in orders:
        st = smap.get(str(o.get("order_status_id")), {})
        color = st.get("color")
        cur = o.get("currency") or "PLN"
        total_f = _bl_total_f(o)
        paid_f = float(o.get("payment_done") or 0)
        rows.append({
            "order_id": o.get("order_id"),
            "external_order_id": o.get("external_order_id") or "",
            "date": _bl_date(o.get("date_add")),
            "date_confirmed": _bl_date(o.get("date_confirmed")),
            "status": st.get("name") or ("status %s" % o.get("order_status_id")),
            "status_color": ("#" + color) if color else "#9ca3af",
            "source": bl_source_label(o.get("order_source")),
            "total": "%.2f" % total_f,
            "currency": cur,
            "delivery": {
                "method": o.get("delivery_method") or "",
                "tracking": o.get("delivery_package_nr") or "",
                "price": "%.2f" % float(o.get("delivery_price") or 0),
                "fullname": o.get("delivery_fullname") or "",
                "company": o.get("delivery_company") or "",
                "address": _bl_delivery_addr(o),
            },
            "payment": {
                "method": o.get("payment_method") or "",
                "paid": "%.2f" % paid_f,
                "due": "%.2f" % max(0.0, total_f - paid_f),
                "is_paid": paid_f + 0.01 >= total_f and total_f > 0,
            },
            "contact": {"phone": o.get("phone") or "", "email": o.get("email") or ""},
            "invoice": {
                "want": bool(o.get("want_invoice") in (1, "1", True)),
                "fullname": o.get("invoice_fullname") or "",
                "company": o.get("invoice_company") or "",
                "nip": o.get("invoice_nip") or "",
                "address": _bl_addr(o, "invoice"),
            },
            "comments": (o.get("user_comments") or "").strip(),
            "items": [{
                "name": p.get("name"),
                "sku": p.get("sku") or "",
                "quantity": p.get("quantity"),
                "price": "%.2f" % float(p.get("price_brutto") or 0),
                "weight": p.get("weight"),
                "auction_id": p.get("auction_id") or "",
            } for p in (o.get("products") or [])],
            "bl_url": "https://panel.baselinker.com/orders.php#order:%s" % o.get("order_id"),
        })
    return jsonify(ok=True, orders=rows)


_BASE_PANEL_HTML = """<!DOCTYPE html>
<html lang="pl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Base</title>
<style>
  *{box-sizing:border-box}
  body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;font-size:13px;color:#1f2933;background:#f8fafc}
  .wrap{padding:10px}.muted{color:#6b7280}.spin{padding:24px;text-align:center;color:#6b7280}
  .empty{padding:24px 10px;text-align:center;color:#6b7280}
  .o{background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:10px;margin-bottom:10px}
  .o-top{display:flex;justify-content:space-between;align-items:center;gap:8px}
  .o-num{font-weight:600}.ext{font-weight:400;color:#6b7280;font-size:12px}
  .badge{display:inline-block;padding:2px 8px;border-radius:999px;color:#fff;font-size:11px;white-space:nowrap}
  .o-meta{font-size:12px;color:#475569;margin-top:3px}
  .pay-ok{color:#16a34a;font-weight:600}.pay-due{color:#d97706;font-weight:600}
  .sec{margin-top:9px}
  .sec-t{font-weight:600;font-size:10px;letter-spacing:.04em;text-transform:uppercase;color:#94a3b8;margin-bottom:3px}
  .kv{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:4px 14px}
  .kv-row{display:flex;flex-direction:column;font-size:12px;line-height:1.25}
  .kv-l{color:#94a3b8;font-size:10px;text-transform:uppercase;letter-spacing:.03em}
  .kv-v{color:#1f2933;word-break:break-word}
  .note{font-size:12px;background:#fff7ed;border:1px solid #fed7aa;border-radius:6px;padding:6px;white-space:pre-wrap}
  .toggle{margin-top:8px;width:100%;background:#fff;border:1px dashed #cbd5e1;color:#475569;border-radius:6px;padding:6px;font-size:12px;cursor:pointer}
  .items{display:none;margin-top:6px}
  .it{border-top:1px solid #eef2f7;padding:5px 0;font-size:12px}.it-s{color:#6b7280;font-size:11px}
  .actions{margin-top:9px}
  .btn{display:block;text-align:center;text-decoration:none;padding:6px 8px;border-radius:6px;font-size:12px;background:#2563eb;color:#fff}
</style></head><body><div class="wrap"><div id="root"><div class="spin">Ladowanie kontekstu rozmowy...</div></div></div>
<script>
  var TOKEN="__BASE_TOKEN__";var root=document.getElementById('root');
  function esc(s){return (s==null?'':String(s)).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});}
  function kv(l,v){return v?'<div class="kv-row"><span class="kv-l">'+esc(l)+'</span><span class="kv-v">'+esc(v)+'</span></div>':'';}
  function section(t,inner){return inner?'<div class="sec"><div class="sec-t">'+esc(t)+'</div><div class="kv">'+inner+'</div></div>':'';}
  root.addEventListener('click',function(ev){
    var b=ev.target.closest?ev.target.closest('.toggle'):null;if(!b)return;
    var box=document.getElementById('it-'+b.getAttribute('data-oid'));if(!box)return;
    if(box.style.display==='block'){box.style.display='none';b.textContent='Pokaz pozycje ▾';}
    else{box.style.display='block';b.textContent='Ukryj pozycje ▴';}
  });
  function render(res){
    if(!res||!res.ok){root.innerHTML='<div class="empty">Blad pobrania zamowien z BaseLinker.</div>';return;}
    if(!res.orders||res.orders.length===0){root.innerHTML='<div class="empty">Brak zamowien dla tego kontaktu.</div>';return;}
    var h='';
    res.orders.forEach(function(o){
      var d=o.delivery||{},p=o.payment||{},c=o.contact||{},inv=o.invoice||{};
      h+='<div class="o">';
      h+='<div class="o-top"><span class="o-num">#'+esc(o.order_id)+(o.external_order_id?' <span class="ext">('+esc(o.external_order_id)+')</span>':'')+'</span>';
      h+='<span class="badge" style="background:'+esc(o.status_color)+'">'+esc(o.status)+'</span></div>';
      h+='<div class="o-meta">'+esc(o.date)+' · '+esc(o.source)+(o.total?' · <b>'+esc(o.total)+' '+esc(o.currency)+'</b>':'');
      if(p.is_paid){h+=' · <span class="pay-ok">Oplacone</span>';}
      else if(p.due&&p.due!=="0.00"){h+=' · <span class="pay-due">Do zaplaty: '+esc(p.due)+' '+esc(o.currency)+'</span>';}
      h+='</div>';
      // Dostawa
      h+=section('Dostawa', kv('Kurier',d.method)+kv('Nr przesylki',d.tracking)+kv('Odbiorca',d.fullname||d.company)+kv('Adres',d.address)+kv('Koszt dostawy',(d.price&&d.price!=="0.00")?d.price+' '+o.currency:''));
      // Platnosc
      h+=section('Platnosc', kv('Metoda',p.method)+kv('Oplacono',(p.paid&&p.paid!=="0.00")?p.paid+' '+o.currency:'')+kv('Do zaplaty',(p.due&&p.due!=="0.00")?p.due+' '+o.currency:''));
      // Klient
      h+=section('Klient', kv('Telefon',c.phone)+kv('E-mail',c.email));
      // Faktura
      if(inv.want||inv.nip||inv.fullname||inv.company){
        h+=section('Faktura', kv('Nazwa',inv.fullname||inv.company)+kv('NIP',inv.nip)+kv('Adres',inv.address)+(inv.want&&!inv.nip&&!inv.fullname?kv('','Klient chce fakture'):''));
      }
      // Uwagi
      if(o.comments){h+='<div class="sec"><div class="sec-t">Uwagi klienta</div><div class="note">'+esc(o.comments)+'</div></div>';}
      // Pozycje
      if(o.items&&o.items.length){
        h+='<button class="toggle" data-oid="'+esc(o.order_id)+'">Pokaz pozycje ('+o.items.length+') ▾</button>';
        h+='<div class="items" id="it-'+esc(o.order_id)+'">';
        o.items.forEach(function(it){
          h+='<div class="it">'+esc(it.name)+' · ×'+esc(it.quantity)+' · '+esc(it.price)+' '+esc(o.currency);
          var extra=[];if(it.sku)extra.push('SKU '+esc(it.sku));if(it.weight)extra.push(esc(it.weight)+' kg');
          if(extra.length)h+='<div class="it-s">'+extra.join(' · ')+(it.auction_id?' · <a target="_blank" rel="noopener" href="https://allegro.pl/oferta/'+esc(it.auction_id)+'">aukcja</a>':'')+'</div>';
          h+='</div>';
        });
        h+='</div>';
      }
      h+='<div class="actions"><a class="btn" target="_blank" rel="noopener" href="'+esc(o.bl_url)+'">Otworz w BaseLinker</a></div>';
      h+='</div>';
    });
    root.innerHTML=h;
  }
  function load(email,phone){
    email=email||'';phone=phone||'';
    if(!email&&!phone){root.innerHTML='<div class="empty">Ta rozmowa nie ma e-maila ani telefonu kontaktu.</div>';return;}
    root.innerHTML='<div class="spin">Szukam zamowien...</div>';
    fetch('/base/api/orders?token='+encodeURIComponent(TOKEN)+'&email='+encodeURIComponent(email)+'&phone='+encodeURIComponent(phone))
      .then(function(r){return r.json();}).then(render)
      .catch(function(){root.innerHTML='<div class="empty">Blad polaczenia z mostem.</div>';});
  }
  window.addEventListener('message',function(event){
    var p=event.data;if(typeof p==='string'){try{p=JSON.parse(p);}catch(e){return;}}
    if(p&&p.event==='appContext'){var c=(p.data||{}).contact||{};load(c.email||'',c.phone_number||'');}
  });
  setTimeout(function(){if(root.querySelector('.spin')){root.innerHTML='<div class="empty">Oczekiwanie na kontekst z Chatwoota...</div>';}},4000);
</script></body></html>"""


@bp.get("/base/panel")
def base_panel():
    if BASE_PANEL_TOKEN and request.args.get("token") != BASE_PANEL_TOKEN:
        return "Brak autoryzacji", 401
    html = _BASE_PANEL_HTML.replace("__BASE_TOKEN__", request.args.get("token", ""))
    resp = current_app.response_class(html, mimetype="text/html")
    resp.headers["Content-Security-Policy"] = "frame-ancestors https://chat.woodpower.pl"
    resp.headers.pop("X-Frame-Options", None)
    return resp
