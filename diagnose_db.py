#!/usr/bin/env python
"""Diagnosticar registros huérfanos en la BD"""

import sqlite3

conn = sqlite3.connect("data/database.db")
c = conn.cursor()

print("\n🔍 DIAGNOSTICO DE REGISTROS HUÉRFANOS\n")

print("1️⃣ Empleados en la BD:")
c.execute("SELECT id, name, employee_number FROM employees")
employees = c.fetchall()
print(f"Total: {len(employees)}")
for emp in employees:
    print(f"  - ID {emp[0]}: {emp[1]} ({emp[2]})")

print("\n2️⃣ face_identities (identidades):")
c.execute("SELECT id FROM face_identities")
identities = c.fetchall()
print(f"Total: {len(identities)}")
for ident in identities:
    print(f"  - ID {ident[0]}")

print("\n3️⃣ face_references (referencias):")
c.execute("SELECT id, employee_id, reference_image_path FROM face_references")
refs = c.fetchall()
print(f"Total: {len(refs)}")
for ref in refs:
    print(f"  - ID {ref[0]}, employee_id {ref[1]}, path: {ref[2]}")

print("\n4️⃣ identity_samples (muestras):")
c.execute("SELECT id, identity_id, employee_id FROM identity_samples")
samples = c.fetchall()
print(f"Total: {len(samples)}")
for samp in samples:
    print(f"  - ID {samp[0]}, identity_id {samp[1]}, employee_id {samp[2]}")

print("\n" + "="*50)
print("ANÁLISIS:")

# Huérfanos en face_references
orphaned_refs = []
for ref in refs:
    exists = any(emp[0] == ref[1] for emp in employees)
    if not exists:
        orphaned_refs.append(ref)

print(f"\n❌ face_references huérfanas (sin employee): {len(orphaned_refs)}")
for ref in orphaned_refs:
    print(f"  - Ref ID {ref[0]}: employee_id {ref[1]}, path: {ref[2]}")

# Huérfanos en face_identities
orphaned_identities = []
for ident in identities:
    c.execute("SELECT COUNT(*) FROM identity_samples WHERE identity_id = ?", (ident[0],))
    count = c.fetchone()[0]
    if count == 0:
        orphaned_identities.append(ident)

print(f"\n❌ face_identities huérfanas (sin samples): {len(orphaned_identities)}")
for ident in orphaned_identities:
    print(f"  - Identity ID {ident[0]}")

conn.close()
