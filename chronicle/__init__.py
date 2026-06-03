#!/usr/bin/env python3
"""
Chronicle Memory Provider Plugin for Hermes Agent.

A graph-native memory system built on LadybugDB (Kuzu fork).
Provides persistent, cross-session knowledge with:
- Fast fact storage (bypass Signal→Candidate pipeline)  
- Multi-stage recall (vector + graph + FTS)
- Pattern detection (hidden connections, communities, gaps)
- Decay lifecycle (exponential decay + access strengthening)

Replaces: ocas-elephas skill, ocas-corvus skill
"""

import os
import json
import time
import hashlib
import logging
import threading
import re
from pathlib import Path
from datetime import datetime, timezone

logger = logging.getLogger('chronicle')

# ── Extension path ──────────────────────────────────────────────────────────
EXT_BASE = Path('/root/.hermes/profiles/indigo/home/.lbdb/extension/0.17.0/linux_amd64')
if EXT_BASE.exists():
    os.environ['LADYBUG_EXTENSION_PATH'] = str(EXT_BASE)

import ladybug as lb


class ChronicleProvider:
    """Hermes Memory Provider plugin for Chronicle graph database."""
    
    def __init__(self):
        self.db_path = None
        self._conn = None
        self._embed_model = None
    
    @property
    def name(self):
        return 'chronicle'
    
    def is_available(self):
        try:
            import ladybug as lb
            return True
        except ImportError:
            return False
    
    def initialize(self, session_id, **kwargs):
        hermes_home = kwargs.get('hermes_home', Path.home() / '.hermes')
        self.db_path = Path(hermes_home) / 'commons' / 'db' / 'chronicle'
        self.db_path.mkdir(parents=True, exist_ok=True)
        
        db_file = self.db_path / 'chronicle.lbug'
        db = lb.Database(str(db_file))
        self._conn = lb.Connection(db)
        
        for ext in ('json', 'vector', 'fts', 'algo'):
            try:
                self._conn.execute(f'INSTALL {ext}')
                self._conn.execute(f'LOAD EXTENSION {ext}')
            except Exception:
                pass
        
        self._ensure_schema()
        logger.info(f'Chronicle initialized: {db_file}')
    
    def _ensure_schema(self):
        try:
            self._conn.execute('MATCH (n:Entity) RETURN count(n)').get_next()
            return
        except Exception:
            pass
        
        node_tables = [
            ('Entity', '''CREATE NODE TABLE IF NOT EXISTS Entity (
                id STRING PRIMARY KEY, name STRING, entity_type STRING,
                aliases STRING DEFAULT '[]', identifiers STRING DEFAULT '[]',
                possible_matches STRING DEFAULT '[]', merge_history STRING DEFAULT '[]',
                identity_state STRING DEFAULT 'distinct',
                source_skill STRING DEFAULT '', record_time STRING DEFAULT '',
                embedding FLOAT[384],
                learned_at INT64 DEFAULT 0, expired_at INT64 DEFAULT 0,
                decay_factor DOUBLE DEFAULT 1.0, access_count INT64 DEFAULT 0,
                updated_at INT64 DEFAULT 0, layer STRING DEFAULT 'domain',
                description STRING DEFAULT '', community_id INT64 DEFAULT -1
            )'''),
            ('Place', '''CREATE NODE TABLE IF NOT EXISTS Place (
                id STRING PRIMARY KEY, name STRING, place_type STRING,
                coordinates STRING DEFAULT '', address STRING DEFAULT '',
                source_skill STRING DEFAULT '', record_time STRING DEFAULT '',
                embedding FLOAT[384],
                learned_at INT64 DEFAULT 0, expired_at INT64 DEFAULT 0,
                decay_factor DOUBLE DEFAULT 1.0, access_count INT64 DEFAULT 0,
                updated_at INT64 DEFAULT 0
            )'''),
            ('Concept', '''CREATE NODE TABLE IF NOT EXISTS Concept (
                id STRING PRIMARY KEY, name STRING, description STRING DEFAULT '',
                concept_type STRING DEFAULT '', event_time STRING DEFAULT '',
                source_skill STRING DEFAULT '', record_time STRING DEFAULT '',
                embedding FLOAT[384],
                learned_at INT64 DEFAULT 0, expired_at INT64 DEFAULT 0,
                decay_factor DOUBLE DEFAULT 1.0, access_count INT64 DEFAULT 0,
                updated_at INT64 DEFAULT 0
            )'''),
            ('Thing', '''CREATE NODE TABLE IF NOT EXISTS Thing (
                id STRING PRIMARY KEY, name STRING, thing_type STRING,
                metadata STRING DEFAULT '', source_skill STRING DEFAULT '',
                record_time STRING DEFAULT '',
                embedding FLOAT[384],
                learned_at INT64 DEFAULT 0, expired_at INT64 DEFAULT 0,
                decay_factor DOUBLE DEFAULT 1.0, access_count INT64 DEFAULT 0,
                updated_at INT64 DEFAULT 0
            )'''),
            ('Signal', '''CREATE NODE TABLE IF NOT EXISTS Signal (
                id STRING PRIMARY KEY, source_skill STRING DEFAULT '',
                source_type STRING DEFAULT '', source_journal_type STRING DEFAULT '',
                payload STRING DEFAULT '', user_relevance STRING DEFAULT 'unknown',
                source_quality STRING DEFAULT 'unverified',
                timestamp STRING DEFAULT '', status STRING DEFAULT 'active',
                embedding FLOAT[384],
                decay_factor DOUBLE DEFAULT 1.0, access_count INT64 DEFAULT 0
            )'''),
            ('Candidate', '''CREATE NODE TABLE IF NOT EXISTS Candidate (
                id STRING PRIMARY KEY, proposed_type STRING DEFAULT '',
                proposed_data STRING DEFAULT '', supporting_signals STRING DEFAULT '',
                confidence STRING DEFAULT 'low', user_relevance STRING DEFAULT 'unknown',
                source_quality STRING DEFAULT 'unverified',
                status STRING DEFAULT 'pending',
                created_at STRING DEFAULT '', resolved_at STRING DEFAULT '',
                resolved_reason STRING DEFAULT '',
                embedding FLOAT[384],
                decay_factor DOUBLE DEFAULT 1.0, access_count INT64 DEFAULT 0
            )'''),
            ('Inference', '''CREATE NODE TABLE IF NOT EXISTS Inference (
                id STRING PRIMARY KEY, inference_type STRING DEFAULT '',
                confidence STRING DEFAULT 'med', supporting_nodes STRING DEFAULT '',
                description STRING DEFAULT '', created_at STRING DEFAULT ''
            )'''),
            ('EdgeNode', '''CREATE NODE TABLE IF NOT EXISTS EdgeNode (
                id STRING PRIMARY KEY, semantic_type STRING DEFAULT '',
                label STRING DEFAULT '', weight DOUBLE DEFAULT 1.0,
                confidence DOUBLE DEFAULT 0.5, provenance STRING DEFAULT 'unknown',
                created_at INT64 DEFAULT 0, expired_at INT64 DEFAULT 0
            )'''),
            ('Cue', '''CREATE NODE TABLE IF NOT EXISTS Cue (
                id STRING PRIMARY KEY, label STRING DEFAULT '',
                cue_type STRING DEFAULT '', embedding FLOAT[384],
                access_count INT64 DEFAULT 0, decay_factor DOUBLE DEFAULT 1.0,
                created_at INT64 DEFAULT 0, expired_at INT64 DEFAULT 0
            )'''),
            ('CommunityMeta', '''CREATE NODE TABLE IF NOT EXISTS CommunityMeta (
                id STRING PRIMARY KEY, community_id INT64 DEFAULT 0,
                size INT64 DEFAULT 0, summary STRING DEFAULT '',
                top_entities STRING DEFAULT '', computed_at INT64 DEFAULT 0,
                embedding FLOAT[384]
            )'''),
            ('Prediction', '''CREATE NODE TABLE IF NOT EXISTS Prediction (
                id STRING PRIMARY KEY, prediction_text STRING DEFAULT '',
                predicted_entity_id STRING DEFAULT '', predicted_outcome STRING DEFAULT '',
                confidence DOUBLE DEFAULT 0.5, status STRING DEFAULT 'pending',
                created_at INT64 DEFAULT 0, resolved_at INT64 DEFAULT 0,
                actual_outcome STRING DEFAULT ''
            )'''),
        ]
        
        for name, ddl in node_tables:
            try:
                self._conn.execute(ddl)
            except Exception:
                pass
        
        rel_tables = [
            ('Relates', '''CREATE REL TABLE IF NOT EXISTS Relates (
                FROM Entity TO Entity, FROM Entity TO Concept,
                FROM Entity TO Place, FROM Entity TO Thing,
                FROM Concept TO Place, FROM Concept TO Concept,
                relationship_type STRING DEFAULT '', evidence_refs STRING DEFAULT '',
                confidence STRING DEFAULT 'med', event_time STRING DEFAULT '',
                record_time STRING DEFAULT '', valid_from STRING DEFAULT '',
                valid_until STRING DEFAULT ''
            )'''),
            ('Supports', 'CREATE REL TABLE IF NOT EXISTS Supports (FROM Signal TO Candidate)'),
            ('Promotes', '''CREATE REL TABLE IF NOT EXISTS Promotes (
                FROM Candidate TO Entity, FROM Candidate TO Place,
                FROM Candidate TO Concept, FROM Candidate TO Thing
            )'''),
            ('Infers', '''CREATE REL TABLE IF NOT EXISTS Infers (
                FROM Inference TO Entity, FROM Inference TO Concept,
                FROM Inference TO Place
            )'''),
            ('CONNECTS', '''CREATE REL TABLE IF NOT EXISTS CONNECTS (
                FROM Entity TO EdgeNode, role STRING DEFAULT 'source'
            )'''),
            ('BINDS', '''CREATE REL TABLE IF NOT EXISTS BINDS (
                FROM EdgeNode TO Entity, role STRING DEFAULT 'target'
            )'''),
            ('EncodedBy', '''CREATE REL TABLE IF NOT EXISTS EncodedBy (
                FROM Thing TO Cue, weight DOUBLE DEFAULT 1.0
            )'''),
            ('CoOccurs', '''CREATE REL TABLE IF NOT EXISTS CoOccurs (
                FROM Cue TO Cue, weight DOUBLE DEFAULT 1.0
            )'''),
        ]
        
        for name, ddl in rel_tables:
            try:
                self._conn.execute(ddl)
            except Exception:
                pass
        
        try:
            self._conn.execute('CALL CREATE_FTS_INDEX("Entity", "entity_fts", ["name", "description"])')
        except Exception:
            pass
    
    def get_tool_schemas(self):
        return [
            {
                'name': 'chronicle_remember',
                'description': 'Store a fact or entity in Chronicle. Fast-path storage.',
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'name': {'type': 'string', 'description': 'Entity name'},
                        'entity_type': {'type': 'string', 'description': 'Type: Person, Place, Concept, Thing, Organization, Event'},
                        'description': {'type': 'string', 'description': 'Description'},
                        'source': {'type': 'string', 'description': 'Source skill'},
                        'relationships': {
                            'type': 'array',
                            'items': {
                                'type': 'object',
                                'properties': {
                                    'target_id': {'type': 'string'},
                                    'relationship_type': {'type': 'string'},
                                }
                            }
                        }
                    },
                    'required': ['name', 'entity_type']
                }
            },
            {
                'name': 'chronicle_query',
                'description': 'Query Chronicle for entities and relationships.',
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'query': {'type': 'string', 'description': 'Search query'},
                        'entity_id': {'type': 'string', 'description': 'Specific entity ID'},
                        'limit': {'type': 'integer', 'default': 10},
                        'mode': {'type': 'string', 'enum': ['search', 'recall', 'list'], 'default': 'search'}
                    }
                }
            },
            {
                'name': 'chronicle_analyze',
                'description': 'Run pattern analysis on the knowledge graph.',
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'mode': {'type': 'string', 'enum': ['light', 'deep', 'hidden_connections', 'gaps'], 'default': 'light'}
                    }
                }
            },
            {
                'name': 'chronicle_status',
                'description': 'Show Chronicle graph health.',
                'parameters': {'type': 'object', 'properties': {}}
            },
        ]
    
    def handle_tool_call(self, tool_name, args, **kwargs):
        try:
            if tool_name == 'chronicle_remember':
                return self._tool_remember(args)
            elif tool_name == 'chronicle_query':
                return self._tool_query(args)
            elif tool_name == 'chronicle_analyze':
                return self._tool_analyze(args)
            elif tool_name == 'chronicle_status':
                return self._tool_status(args)
            else:
                return {'error': f'Unknown tool: {tool_name}'}
        except Exception as e:
            return {'error': str(e)}
    
    def _tool_remember(self, args):
        name = args.get('name', '')
        entity_type = args.get('entity_type', 'Entity')
        description = args.get('description', '')
        source = args.get('source', 'agent')
        eid = self._store_entity(name, entity_type, description, source)
        for rel in args.get('relationships', []):
            self._create_relationship(eid, rel.get('target_id', ''), rel.get('relationship_type', 'related_to'))
        return {'id': eid, 'name': name, 'type': entity_type, 'stored': True}
    
    def _tool_query(self, args):
        query = args.get('query', '')
        entity_id = args.get('entity_id', '')
        limit = args.get('limit', 10)
        mode = args.get('mode', 'search')
        if entity_id:
            return self._get_entity(entity_id)
        if query:
            return self._search(query, limit, mode)
        return self._list_recent(limit)
    
    def _tool_analyze(self, args):
        mode = args.get('mode', 'light')
        if mode == 'hidden_connections':
            return {'hidden_connections': self._detect_hidden_connections()[:20]}
        elif mode == 'gaps':
            return {'gaps': self._detect_gaps()[:20]}
        return {'stats': self._get_stats()}
    
    def _tool_status(self, args):
        return self._get_stats()
    
    def _gen_id(self, prefix='ent'):
        ts = int(time.time() * 1000) % 1000000
        rand = hashlib.md5(os.urandom(8)).hexdigest()[:8]
        return f'{prefix}_{ts}_{rand}'
    
    def _store_entity(self, name, entity_type, description='', source='agent'):
        eid = self._gen_id('ent')
        now = datetime.now(timezone.utc).isoformat()
        now_ts = int(time.time())
        text = f'{name}. {entity_type}. {description}'[:2000]
        emb = self._get_embedding(text)
        emb_json = json.dumps(emb) if emb else None
        
        safe_name = name.replace("'", "\\'")[:500]
        safe_type = entity_type.replace("'", "\\'")
        safe_desc = description.replace("'", "\\'")[:500] if description else ''
        
        if emb_json:
            self._conn.execute(f'''
                CREATE (e:Entity {{
                    id: '{eid}', name: '{safe_name}', entity_type: '{safe_type}',
                    aliases: '[]', identifiers: '{{}}', possible_matches: '[]',
                    merge_history: '[]', identity_state: 'distinct',
                    source_skill: '{source}', record_time: '{now}',
                    embedding: {emb_json},
                    learned_at: {now_ts}, expired_at: 0, decay_factor: 1.0,
                    access_count: 0, updated_at: {now_ts},
                    layer: 'user', description: '{safe_desc}', community_id: -1
                }})
            ''')
        else:
            self._conn.execute(f'''
                CREATE (e:Entity {{
                    id: '{eid}', name: '{safe_name}', entity_type: '{safe_type}',
                    aliases: '[]', identifiers: '{{}}', possible_matches: '[]',
                    merge_history: '[]', identity_state: 'distinct',
                    source_skill: '{source}', record_time: '{now}',
                    learned_at: {now_ts}, expired_at: 0, decay_factor: 1.0,
                    access_count: 0, updated_at: {now_ts},
                    layer: 'user', description: '{safe_desc}', community_id: -1
                }})
            ''')
        return eid
    
    def _create_relationship(self, source_id, target_id, rel_type):
        now = datetime.now(timezone.utc).isoformat()
        try:
            self._conn.execute(f'''
                MATCH (a:Entity {{id: '{source_id}'}}),
                      (b:Entity {{id: '{target_id}'}})
                MERGE (a)-[r:Relates {{relationship_type: '{rel_type}'}}]->(b)
                ON CREATE SET r.confidence = 'med', r.record_time = '{now}'
            ''')
        except Exception:
            pass
    
    def _get_embedding(self, text):
        try:
            if self._embed_model is None:
                from fastembed import TextEmbedding
                self._embed_model = TextEmbedding(model_name='BAAI/bge-small-en-v1.5')
            return list(self._embed_model.embed([text[:2000]]))[0].tolist()
        except Exception:
            return None
    
    def _get_entity(self, entity_id):
        try:
            r = self._conn.execute(f'MATCH (e:Entity {{id: "{entity_id}"}}) RETURN e')
            if r.has_next():
                return self._node_to_dict(r.get_all()[0][0])
        except Exception:
            pass
        return None
    
    def _search(self, query, limit=10, mode='search'):
        results = []
        safe_query = query.replace("'", "\\'")[:200]
        
        try:
            r = self._conn.execute(f'''
                MATCH (e:Entity)
                WHERE e.name CONTAINS '{safe_query}'
                   OR e.description CONTAINS '{safe_query}'
                RETURN e, 1.0 as score
                ORDER BY e.decay_factor DESC LIMIT {limit}
            ''')
            for row in r.get_all():
                d = self._node_to_dict(row[0])
                if d:
                    d['score'] = row[1] if len(row) > 1 else 1.0
                    d['match_type'] = 'text'
                    results.append(d)
        except Exception:
            pass
        
        emb = self._get_embedding(query)
        if emb and len(results) < limit:
            try:
                emb_json = json.dumps(emb)
                r = self._conn.execute(f'''
                    MATCH (e:Entity)
                    WHERE e.embedding IS NOT NULL
                    WITH e, array_cosine_similarity(e.embedding, {emb_json}) AS score
                    WHERE score > 0.5
                    RETURN e, score
                    ORDER BY score DESC LIMIT {limit}
                ''')
                existing_ids = {r['id'] for r in results}
                for row in r.get_all():
                    d = self._node_to_dict(row[0])
                    if d and d.get('id') not in existing_ids:
                        d['score'] = float(row[1])
                        d['match_type'] = 'vector'
                        results.append(d)
            except Exception:
                pass
        
        results.sort(key=lambda x: x.get('score', 0), reverse=True)
        return results[:limit]
    
    def _list_recent(self, limit=10):
        try:
            r = self._conn.execute(f'''
                MATCH (e:Entity) WHERE e.name IS NOT NULL
                RETURN e ORDER BY e.learned_at DESC LIMIT {limit}
            ''')
            return [self._node_to_dict(row[0]) for row in r.get_all()]
        except Exception:
            return []
    
    def _node_to_dict(self, node):
        if node is None:
            return {}
        if isinstance(node, dict):
            return {k: v for k, v in node.items() if not k.startswith('_')}
        try:
            result = {}
            for attr in ['id', 'name', 'entity_type', 'description', 'source_skill',
                        'record_time', 'identity_state', 'layer', 'confidence',
                        'place_type', 'thing_type', 'concept_type', 'status',
                        'user_relevance', 'decay_factor', 'access_count']:
                try:
                    val = getattr(node, attr, None)
                    if val is not None:
                        result[attr] = val
                except Exception:
                    pass
            return result
        except Exception:
            return {}
    
    def _detect_hidden_connections(self, top_n=20):
        r = self._conn.execute('''
            MATCH (e:Entity)
            WHERE e.embedding IS NOT NULL AND e.name IS NOT NULL
            RETURN e.id, e.name, e.entity_type, e.embedding
        ''')
        entities = []
        for row in r.get_all():
            if row[0] and row[3]:
                emb = row[3] if isinstance(row[3], list) else json.loads(row[3]) if isinstance(row[3], str) else None
                if emb:
                    entities.append({'id': row[0], 'name': row[1], 'type': row[2], 'embedding': emb})
        
        hidden = []
        seen = set()
        for i, a in enumerate(entities):
            for j, b in enumerate(entities):
                if i >= j:
                    continue
                pair_key = f'{a["id"]}|{b["id"]}'
                if pair_key in seen:
                    continue
                seen.add(pair_key)
                
                try:
                    r = self._conn.execute(f'''
                        MATCH (a:Entity {{id: "{a["id"]}"}})-[:Relates]-(b:Entity {{id: "{b["id"]}"}})
                        RETURN count(*) as cnt
                    ''')
                    if r.has_next() and r.get_all()[0][0] > 0:
                        continue
                except Exception:
                    continue
                
                try:
                    emb_a, emb_b = a['embedding'], b['embedding']
                    dot = sum(x * y for x, y in zip(emb_a, emb_b))
                    norm_a = sum(x * x for x in emb_a) ** 0.5
                    norm_b = sum(x * x for x in emb_b) ** 0.5
                    if norm_a > 0 and norm_b > 0:
                        sim = dot / (norm_a * norm_b)
                        if sim > 0.7:
                            hidden.append({
                                'source': {'id': a['id'], 'name': a['name'], 'type': a.get('type', '')},
                                'target': {'id': b['id'], 'name': b['name'], 'type': b.get('type', '')},
                                'similarity': round(sim, 4)
                            })
                except Exception:
                    continue
        
        hidden.sort(key=lambda x: x['similarity'], reverse=True)
        return hidden[:top_n]
    
    def _detect_gaps(self, limit=20):
        try:
            r = self._conn.execute('''
                MATCH (e:Entity)-[:Relates]-()
                WITH e, count(*) as degree
                WHERE degree >= 2
                RETURN e.id, e.name, e.entity_type, degree
                ORDER BY degree DESC LIMIT 50
            ''')
            high_degree = [{'id': row[0], 'name': row[1], 'type': row[2], 'degree': row[3]}
                          for row in r.get_all()]
            gaps = []
            for i, a in enumerate(high_degree):
                for b in high_degree[i+1:]:
                    try:
                        r = self._conn.execute(f'''
                            MATCH (a:Entity {{id: "{a["id"]}"}})-[:Relates]-(b:Entity {{id: "{b["id"]}"}})
                            RETURN count(*) as cnt
                        ''')
                        if r.has_next() and r.get_all()[0][0] == 0:
                            gaps.append({
                                'source': {'id': a['id'], 'name': a['name']},
                                'target': {'id': b['id'], 'name': b['name']},
                                'gap_score': a['degree'] + b['degree']
                            })
                    except Exception:
                        continue
            gaps.sort(key=lambda x: x['gap_score'], reverse=True)
            return gaps[:limit]
        except Exception:
            return []
    
    def _get_stats(self):
        stats = {}
        for label in ['Entity', 'Place', 'Concept', 'Thing', 'Signal', 'Candidate',
                      'Inference', 'EdgeNode', 'Cue', 'Relates', 'Supports', 'Promotes']:
            try:
                r = self._conn.execute(f'MATCH (n:{label}) RETURN count(n)')
                stats[label.lower() + '_count'] = r.get_all()[0][0] if r.has_next() else 0
            except Exception:
                stats[label.lower() + '_count'] = 0
        try:
            r = self._conn.execute('MATCH (e:Entity) WHERE e.embedding IS NOT NULL RETURN count(e)')
            stats['entities_with_embeddings'] = r.get_all()[0][0] if r.has_next() else 0
        except Exception:
            stats['entities_with_embeddings'] = 0
        return stats
    
    def system_prompt_block(self):
        return 'Chronicle Memory: Graph-based long-term memory. Use chronicle_remember to store facts, chronicle_query to search.'
    
    def prefetch(self, query, *, session_id=''):
        if not query or len(query.strip()) < 2:
            return ''
        results = self._search(query, limit=5, mode='search')
        if not results:
            return ''
        lines = ['## Relevant Knowledge']
        for r in results[:5]:
            name = r.get('name', 'Unknown')
            etype = r.get('entity_type', '')
            score = r.get('score', 0)
            parts = [f'- {name}']
            if etype:
                parts.append(f'({etype})')
            parts.append(f'[{score:.2f}]')
            lines.append(' '.join(parts))
        return '\n'.join(lines)
    
    def sync_turn(self, user_content, assistant_content, *, session_id='', messages=None):
        def _sync():
            try:
                text = f'{user_content} {assistant_content}'
                names = re.findall(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\b', text)
                skip_words = {'the', 'and', 'for', 'this', 'that', 'with', 'from', 'have', 'will', 'what', 'when', 'where', 'which', 'could', 'would', 'should', 'there', 'their', 'about', 'while', 'were', 'been', 'being', 'them', 'they', 'then', 'than', 'just', 'also', 'some', 'more', 'very', 'only', 'over', 'under', 'each', 'such', 'both', 'because', 'between', 'using', 'used', 'user', 'agent', 'good', 'great', 'nice', 'well', 'like', 'know', 'think', 'make', 'take'}
                for name in set(names):
                    if name.lower() in skip_words or len(name) < 3:
                        continue
                    safe_name = name.replace("'", "\\'")
                    try:
                        r = self._conn.execute(f'MATCH (e:Entity {{name: "{safe_name}"}}) RETURN e.id')
                        if not r.has_next():
                            self._store_entity(name, 'Unknown', 'From conversation', 'sync')
                    except Exception:
                        continue
            except Exception as e:
                logger.warning(f'sync_turn: {e}')
        
        t = threading.Thread(target=_sync, daemon=True)
        t.start()
    
    def shutdown(self):
        try:
            if self._conn:
                self._conn.close()
        except Exception:
            pass


def register(ctx):
    ctx.register_memory_provider(ChronicleProvider())
