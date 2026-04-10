"""
Diagnóstico de FALSOS POSITIVOS en el sistema de verificación biométrica.

Analiza:
1. Embeddings guardados en todos los empleados
2. Cálculo manual de similitud entre todos los pares
3. Verificación de verificación_logs para identificar inconsistencias
"""
import json
import sqlite3
import numpy as np
import pandas as pd
from settings import SETTINGS
from typing import List, Dict, Tuple

def cosine_similarity(emb1, emb2):
    """Calcula similitud coseno entre dos embeddings."""
    norm1 = emb1 / np.linalg.norm(emb1)
    norm2 = emb2 / np.linalg.norm(emb2)
    return np.dot(norm1, norm2)

def get_db_connection():
    conn = sqlite3.connect(SETTINGS.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def analyze_embeddings():
    """Analiza todos los embeddings y calcula similitudes entre empleados."""
    conn = get_db_connection()
    c = conn.cursor()
    
    # Obtener todos los embedded samples con información del empleado
    c.execute("""
        SELECT 
            e.id as employee_id,
            e.employee_number,
            e.name,
            idsamps.id as sample_id,
            idsamps.embedding_json
        FROM employees e
        JOIN face_identities fi ON e.face_identity_id = fi.id
        JOIN identity_samples idsamps ON fi.id = idsamps.identity_id
        ORDER BY e.id, idsamps.id
    """)
    
    rows = c.fetchall()
    
    # Organizar por empleado
    embeddings_by_employee = {}
    for row in rows:
        emp_id = row['employee_id']
        emp_number = row['employee_number']
        emp_name = row['name']
        
        if emp_id not in embeddings_by_employee:
            embeddings_by_employee[emp_id] = {
                'employee_number': emp_number,
                'name': emp_name,
                'embeddings': []
            }
        
        try:
            emb = np.array(json.loads(row['embedding_json']), dtype=np.float32)
            embeddings_by_employee[emp_id]['embeddings'].append(emb)
        except Exception as e:
            print(f"❌ Error parsing embedding for employee {emp_number}: {e}")
    
    print("\n" + "="*80)
    print("RESUMEN DE EMBEDDINGS GUARDADOS")
    print("="*80)
    print(f"\nTotal de empleados con embeddings: {len(embeddings_by_employee)}")
    for emp_id, data in embeddings_by_employee.items():
        print(f"  - {data['employee_number']} ({data['name']}: {len(data['embeddings'])} samples")
    
    # Calcular similitudes entre todos los pares
    print("\n" + "="*80)
    print("ANÁLISIS DE SIMILITUD ENTRE EMPLOYADOS")
    print("="*80)
    print("\nFórmula: similitud = PromedioDeSimilitudDeTodosLosPares")
    print("Threshold: 0.45 (distancia = 1 - similitud)")
    print()
    
    employee_ids = sorted(embeddings_by_employee.keys())
    high_similarity_pairs = []  # Pares con alta similitud
    
    for i, emp_id1 in enumerate(employee_ids):
        for emp_id2 in employee_ids[i+1:]:
            emp1_data = embeddings_by_employee[emp_id1]
            emp2_data = embeddings_by_employee[emp_id2]
            
            # Calcular similitud máxima entre cualquier par de samples
            similarities = []
            for emb1 in emp1_data['embeddings']:
                for emb2 in emp2_data['embeddings']:
                    sim = cosine_similarity(emb1, emb2)
                    similarities.append(sim)
            
            max_similarity = max(similarities) if similarities else 0
            min_similarity = min(similarities) if similarities else 0
            avg_similarity = np.mean(similarities) if similarities else 0
            
            # Convertir a distancia (como el código)
            avg_distance = 1.0 - avg_similarity if avg_similarity > 0 else 1.0
            
            print(f"\n{emp1_data['employee_number']} ({emp1_data['name']}) " +
                  f"vs " +
                  f"{emp2_data['employee_number']} ({emp2_data['name']})")
            print(f"  Max similarity: {max_similarity:.4f} (distance: {1-max_similarity:.4f})")
            print(f"  Avg similarity: {avg_similarity:.4f} (distance: {avg_distance:.4f})")
            print(f"  Min similarity: {min_similarity:.4f} (distance: {1-min_similarity:.4f})")
            
            # Marcar si el promedio sería un FALSO POSITIVO con threshold 0.45
            if avg_distance <= 0.45:
                print(f"  ⚠️  ALERTA: Promedio pasaría threshold 0.45!")
                high_similarity_pairs.append((emp1_data, emp2_data, avg_similarity, avg_distance))
            elif max_similarity >= 0.55:  # distancia <= 0.45
                print(f"  ⚠️  ALERTA: Máxima similitud pasaría threshold!")
                high_similarity_pairs.append((emp1_data, emp2_data, max_similarity, 1-max_similarity))
    
    # Resumen de alertas
    print("\n" + "="*80)
    print("PARES CON ALTO RIESGO DE FALSO POSITIVO (similitud > 0.55)")
    print("="*80)
    if high_similarity_pairs:
        for emp1, emp2, sim, dist in sorted(high_similarity_pairs, key=lambda x: x[2], reverse=True):
            print(f"\n🚨 {emp1['employee_number']} vs {emp2['employee_number']}")
            print(f"   Similitud: {sim:.4f} | Distancia: {dist:.4f}")
    else:
        print("✅ No se encontraron pares con alto riesgo")
    
    conn.close()
    return embeddings_by_employee, high_similarity_pairs

def analyze_verification_logs():
    """Analiza los logs de verificación para encontrar inconsistencias."""
    conn = get_db_connection()
    c = conn.cursor()
    
    # Obtener todos los verification logs recientes
    c.execute("""
        SELECT 
            vl.id,
            vl.employee_id,
            vl.distance,
            vl.threshold_used,
            vl.matched,
            vl.created_at,
            e.employee_number,
            e.name
        FROM verification_logs vl
        LEFT JOIN employees e ON vl.employee_id = e.id
        ORDER BY vl.created_at DESC
        LIMIT 50
    """)
    
    rows = c.fetchall()
    
    print("\n" + "="*80)
    print("ÚLTIMOS 50 VERIFICACIÓN LOGS")
    print("="*80)
    
    data = []
    for row in rows:
        data.append({
            'ID': row['id'],
            'Employee #': row['employee_number'] or 'NULL',
            'Name': row['name'] or 'NULL',
            'Distance': f"{row['distance']:.4f}" if row['distance'] else 'NULL',
            'Threshold': f"{row['threshold_used']:.2f}",
            'Matched': '✅ SÍ' if row['matched'] else '❌ NO',
            'Timestamp': row['created_at']
        })
    
    if data:
        df = pd.DataFrame(data)
        print(df.to_string(index=False))
    else:
        print("No hay logs")
    
    # Análisis de falsos positivos en logs
    print("\n" + "="*80)
    print("ANÁLISIS DE FALSOS POSITIVOS EN LOGS")
    print("="*80)
    
    c.execute("""
        SELECT 
            COUNT(*) as total_logs,
            SUM(CASE WHEN matched = 1 THEN 1 ELSE 0 END) as True_Positive,
            SUM(CASE WHEN matched = 0 THEN 1 ELSE 0 END) as True_Negative
        FROM verification_logs
    """)
    
    stats = c.fetchone()
    print(f"\nTotal verificaciones: {stats['total_logs']}")
    print(f"Acceso permitido: {stats['True_Positive']}")
    print(f"Acceso denegado: {stats['True_Negative']}")
    
    # Buscar casos donde distance > threshold pero matched = 1
    c.execute("""
        SELECT 
            vl.id,
            vl.distance,
            vl.threshold_used,
            vl.matched,
            e.employee_number,
            e.name
        FROM verification_logs vl
        LEFT JOIN employees e ON vl.employee_id = e.id
        WHERE vl.distance > vl.threshold_used AND vl.matched = 1
    """)
    
    inconsistent = c.fetchall()
    if inconsistent:
        print("\n" + "⚠️  INCONSISTENCIAS CRÍTICAS (distance > threshold pero matched=1):")
        for row in inconsistent:
            print(f"  - Log {row['id']}: emp {row['employee_number']} - distance={row['distance']:.4f} > threshold={row['threshold_used']:.2f}")
    else:
        print("\n✅ No hay inconsistencias en los logs")
    
    conn.close()

def check_embedding_quality():
    """Verifica la calidad de los embeddings guardados."""
    conn = get_db_connection()
    c = conn.cursor()
    
    c.execute("""
        SELECT 
            e.employee_number,
            e.name,
            COUNT(idsamps.id) as num_samples,
            AVG(LENGTH(idsamps.embedding_json)) as avg_embedding_size
        FROM employees e
        JOIN face_identities fi ON e.face_identity_id = fi.id
        JOIN identity_samples idsamps ON fi.id = idsamps.identity_id
        GROUP BY e.id
    """)
    
    rows = c.fetchall()
    
    print("\n" + "="*80)
    print("CALIDAD DE EMBEDDINGS GUARDADOS")
    print("="*80)
    
    for row in rows:
        print(f"\n{row['employee_number']} ({row['name']})")
        print(f"  Samples: {row['num_samples']}")
        print(f"  Avg embedding size (bytes): {row['avg_embedding_size']:.0f}")
    
    conn.close()

if __name__ == "__main__":
    print("\n🔍 Iniciando diagnóstico de FALSOS POSITIVOS...")
    
    # Análisis 1: Embeddings
    embeddings, high_risks = analyze_embeddings()
    
    # Análisis 2: Calidad
    check_embedding_quality()
    
    # Análisis 3: Logs
    analyze_verification_logs()
    
    print("\n" + "="*80)
    print("✅ DIAGNÓSTICO COMPLETADO")
    print("="*80)
