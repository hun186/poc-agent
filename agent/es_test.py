from elasticsearch import Elasticsearch
ES = Elasticsearch("http://localhost:9200")
from tools_es import RUNTIME_MAPPINGS

'''
RUNTIME_MAPPINGS = {
    "subject_rt": {
        "type": "keyword",
        "script": {"source": """
          def c = params._source['communication'];
          if (c != null) { def s = c['subject']; if (s != null) emit(s); }
        """}
    },
    "content_rt": {
        "type": "keyword",
        "script": {"source": """
          def r = params._source['rawInfo'];
          if (r != null) { def t = r['content']; if (t != null) emit(t); }
        """}
    },

    # ★ 改成輸出 epoch millis
    "event_dt_rt": {
      "type": "date",
      "format": "yyyy-MM-dd||yyyy-MM||yyyy",
      "script": {
        "source": """
          def blocks = params._source['multidim_event_json'];
          if (blocks == null) return;
          def blocksArr = (blocks instanceof List) ? blocks : [blocks];
    
          int count = 0;  // ← 計數器
    
          for (def b : blocksArr) {
            if (b == null) continue;
            def tl = b['Event_Timeline'];
            if (tl == null) continue;
            def tlArr = (tl instanceof List) ? tl : [tl];
    
            for (def t : tlArr) {
              if (t == null) continue;
              def d = t['date_iso'];
              if (d == null) continue;
    
              String x = d.toString().trim();
              if (x.length() == 0) continue;
    
              x = x.replace('/', '-').replace('／', '-').replace('.', '-')
                   .replace('年', '-').replace('月', '-').replace('日', '');
    
              if (x.length() < 4) continue;
              String yy = x.substring(0, 4);
    
              boolean okYear = true;
              for (int i = 0; i < 4; i++) {
                int cp = yy.codePointAt(i);
                if (cp < 48 || cp > 57) { okYear = false; break; }
              }
              if (!okYear) continue;
    
              String mm = null;
              String dd = null;
              int p1 = x.indexOf('-');
              if (p1 > 0) {
                int p2 = x.indexOf('-', p1 + 1);
                if (p2 > 0) { mm = x.substring(p1 + 1, p2); dd = x.substring(p2 + 1); }
                else        { mm = x.substring(p1 + 1); }
              }
              if (mm != null && mm.length() == 1) mm = '0' + mm;
              if (dd != null && dd.length() == 1) dd = '0' + dd;
    
              int y  = Integer.parseInt(yy);
              int mo = (mm != null && mm.length() > 0) ? Integer.parseInt(mm) : 1;
              int da = (dd != null && dd.length() > 0) ? Integer.parseInt(dd) : 1;
    
              def zdt = java.time.ZonedDateTime.of(y, mo, da, 0, 0, 0, 0, java.time.ZoneId.of("UTC"));
              emit(zdt.toInstant().toEpochMilli());
    
              // ★ 超過 100 就停
              count++;
              if (count >= 100) return;
            }
          }
        """
      }
    },

    "event_year_rt": {
      "type": "keyword",
      "script": {
        "source": """
          def blocks = params._source['multidim_event_json'];
          if (blocks == null) return;
          def blocksArr = (blocks instanceof List) ? blocks : [blocks];
    
          def years = new java.util.HashSet();  // ← 去重
          for (def b : blocksArr) {
            if (b == null) continue;
            def tl = b['Event_Timeline'];
            if (tl == null) continue;
            def tlArr = (tl instanceof List) ? tl : [tl];
    
            for (def t : tlArr) {
              if (t == null) continue;
              def d = t['date_iso'];
              if (d == null) continue;
    
              String s = d.toString();
              if (s.length() < 4) continue;
              String y = s.substring(0, 4);
    
              boolean ok = true;
              for (int i = 0; i < 4; i++) {
                int cp = y.codePointAt(i);
                if (cp < 48 || cp > 57) { ok = false; break; }
              }
              if (!ok) continue;
    
              years.add(y);
              if (years.size() >= 100) break;   // ★ 上限
            }
            if (years.size() >= 100) break;
          }
    
          for (def y : years) emit(y);
        """
      }
    }
}
'''
body = {
  "size": 5,
  "_source": ["uuid","communication.subject"],
  "runtime_mappings": {
    "subject_rt": {
      "type": "keyword",
      "script": { "source": """
        def c = params._source['communication'];
        if (c != null) {
          def s = c['subject'];
          if (s != null) emit(s);
        }
      """}
    },
    "content_rt": {
      "type": "keyword",
      "script": { "source": """
        def r = params._source['rawInfo'];
        if (r != null) {
          def t = r['content'];
          if (t != null) emit(t);
        }
      """}
    }
  },
  "query": {
    "script": {
      "script": {
        "lang": "painless",
        "params": {"q": "家具關稅"},
        "source": """
          String s = (doc.containsKey('subject_rt') && !doc['subject_rt'].empty)
                     ? doc['subject_rt'].value : null;
          String c = (doc.containsKey('content_rt') && !doc['content_rt'].empty)
                     ? doc['content_rt'].value : null;
          if (s == null && c == null) return false;
          boolean hit = false;
          if (!hit && s != null && s.contains(params.q)) hit = true;
          if (!hit && c != null && c.contains(params.q)) hit = true;
          if (!hit) {
            boolean okS = (s != null && s.contains('家具') && s.contains('關稅'));
            boolean okC = (c != null && c.contains('家具') && c.contains('關稅'));
            if (okS || okC) hit = true;
          }
          return hit;
        """
      }
    }
  }
}

print(ES.search(index="news_test", body=body))

try:
    ES.search(index="news_test", body={
        "size": 1,
        "runtime_mappings": RUNTIME_MAPPINGS,
        "query": {"term": {"event_year_rt": "2024"}},
        "_source": False
    })
except Exception as e:
    import json, sys
    detail = getattr(e, "body", getattr(e, "info", {}))
    print(json.dumps(detail, ensure_ascii=False, indent=2), file=sys.stderr)
    

# 1) 僅以 runtime 年份過濾、完全不看文字
ES.search(index="news_test", body={
    "size": 5,
    "runtime_mappings": RUNTIME_MAPPINGS,
    "query": {"term": {"event_year_rt": "2024"}},
    "_source": ["uuid","communication.subject"]
})

# 2) 用事件日期 range
ES.search(index="news_test", body={
    "size": 5,
    "runtime_mappings":RUNTIME_MAPPINGS,
    "query": {"range": {"event_dt_rt": {"gte": "2024-01-01", "lte": "2024-12-31"}}},
    "_source": ["uuid","communication.subject"]
})

from tools_es import ESSearchNews
t = ESSearchNews()
# 這兩個理論上不會回同一筆（除非該文件同時含 2022 與 2024）
print("~"*50)
print("貿易")
print(t.forward(query="請整理貿易相關的重點事件", size=5))
print("~"*50)
print("2024 拉拉隊-1")
print(t.forward(query="請整理 2024 拉拉隊 相關的重點事件", size=5))
print("~"*50)
print("2022 拉拉隊")
print(t.forward(query="請整理 2022 拉拉隊 相關的重點事件", size=5))
print("~"*50)
print("2024 拉拉隊-2")
print(t.forward(query="拉拉隊", date_from="2024-01-01", date_to="2024-12-31", size=5))