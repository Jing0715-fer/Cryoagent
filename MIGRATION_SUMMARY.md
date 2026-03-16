# PDF and Appendix Storage Path Unification - Implementation Summary

## Overview
This implementation unifies the storage paths for PDF files and appendices into a consistent structure: `literature/pdfs/{literature_id}/`

## Changes Made

### Phase 1: File Migration (Completed)

#### Migrated Files
| ID | Title | Source Path | New Path |
|----|-------|-------------|----------|
| 1 | Ubiquitin ligation to F-box protein targets... | `/mnt/d/script/agent/literature_agent/literature/pdfs/s41586-021-03197-9.pdf` | `literature/pdfs/1/main.pdf` |
| 2 | Functional and epitope specific monoclonal antibody... | `/mnt/d/script/agent/literature_agent/literature/pdfs/sciadv.adv8257.pdf` | `literature/pdfs/2/main.pdf` |
| 3 | In situ structure of the mouse sperm central apparatus... | `/mnt/d/script/agent/literature_agent/literature/pdfs/s41422-025-01135-2.pdf` | `literature/pdfs/3/main.pdf` |
| 4 | Cryo-EM structure of human GPR158 receptor... | `/mnt/d/script/agent/literature_agent/literature/pdfs/science.abl4732.pdf` | `literature/pdfs/4/main.pdf` |
| 5 | Structure of the class C orphan GPCR GPR158... | `/mnt/d/script/agent/literature_agent/literature/pdfs/s41467-021-27147-1.pdf` | `literature/pdfs/5/main.pdf` |
| 6 | Cryo-EM structure of human class C orphan GPCR GPR179... | `/mnt/d/script/agent/literature_agent/literature/pdfs/s41467-024-52584-z.pdf` | `literature/pdfs/6/main.pdf` |
| 7 | Cryo-EM structures reveal the acetylation process... | `/mnt/d/script/agent/literature_agent/literature/pdfs/wang-et-al-2025-cryo-em-structures-reveal-the-acetylation-process-of-piccolo-nua4.pdf` | `literature/pdfs/7/main.pdf` |
| 8 | Structures of human γδ T cell receptor–CD3 complex... | `/mnt/d/script/agent/literature_agent/literature/pdfs/s41586-024-07439-4.pdf` | `literature/pdfs/8/main.pdf` |
| 9 | TIR domains of plant immune receptors... | `/mnt/d/script/agent/literature_agent/literature/pdfs/1-s2.0-S009286742200530X-main.pdf` | `literature/pdfs/9/main.pdf` |
| 10 | Structure of the thrombopoietin-MPL receptor complex... | `/mnt/d/script/agent/literature_agent/literature/pdfs/PIIS0092867423008528.pdf` | `literature/pdfs/10/main.pdf` |
| 11 | Systematic metabolite screening identifies... | `/mnt/d/script/agent/literature_agent-V2/literature/pdfs/s42004-025-01825-3_reference (1).pdf` | `literature/pdfs/11/main.pdf` |
| 12 | Activation of the helper NRC4 immune receptor... | `/mnt/d/script/agent/literature_agent-V2-test/literature/pdfs/PIIS0092867424007736.pdf` | `literature/pdfs/12/main.pdf` |
| 14 | ChAdOx1 interacts with CAR and PF4... | `uploads/9bbe4105d89c4ca79ab350318ccc5c30_sciadv.abl8213.pdf` | `literature/pdfs/14/main.pdf` |
| 15 | Molecular mechanisms of receptor recognition... | `uploads/5ef38d5309914aff9db1ae05e9bbef43_CA62.pdf` | `literature/pdfs/15/main.pdf` |
| 16 | Highly ordered clustering of TNFα and BAFF... | `uploads/172ff0444163492d982d6ecf06873acc_s41467-025-61271-6.pdf` | `literature/pdfs/16/main.pdf` |
| 17 | Mechanism of degrader-targeted protein ubiquitinability... | `uploads/f8e5f4a6424e49e5bd983a6826367a48_sciadv.ado6492.pdf` | `literature/pdfs/17/main.pdf` |

#### Migrated Appendix
| ID | Literature ID | Filename | New Path |
|----|---------------|----------|----------|
| 1 | 3 | science.adm8684_sm_4.pdf | `literature/pdfs/3/appendix_science.adm8684_sm_4.pdf` |

### Phase 2: Code Modifications (Completed)

#### Modified Files

1. **routes/upload.py**
   - Added `shutil` import for file operations
   - Modified upload flow to use temporary storage first (`uploads/`)
   - After successful database insertion, PDF is moved to `literature/pdfs/{literature_id}/main.pdf`
   - Database path is updated after file move
   - Added cleanup logic for failed uploads

2. **routes/literature.py**
   - Modified appendix upload to save to `literature/pdfs/{literature_id}/`
   - Appendix files now use `appendix_` prefix: `appendix_{filename}`
   - Updated database record to use the new filename with prefix

### Phase 3: Verification (Completed)

#### Directory Structure
```
literature/pdfs/
├── 1/
│   └── main.pdf
├── 2/
│   └── main.pdf
├── 3/
│   ├── main.pdf
│   └── appendix_science.adm8684_sm_4.pdf
├── ...
├── 17/
│   └── main.pdf
```

#### Database Verification
- All 16 literature entries (IDs 1-12, 14-17) now have updated paths
- Appendix entry for ID 3 updated to new path
- All paths point to `/mnt/d/script/agent/literature_agent-V2-claude/Cryoagent/literature/pdfs/{id}/`

## New Storage Convention

### Main PDF Files
- **Location:** `literature/pdfs/{literature_id}/main.pdf`
- **Naming:** Always `main.pdf` (consistent, easy to find)
- **Migration:** Automatically moved after database insertion

### Appendix Files
- **Location:** `literature/pdfs/{literature_id}/`
- **Naming:** `appendix_{original_filename}` (prefixed to distinguish from main PDF)
- **Example:** `appendix_supplementary_data.pdf`

## Backward Compatibility

The existing code in `routes/literature.py` maintains backward compatibility:
- File lookup tries multiple locations in order:
  1. Database stored path (new location)
  2. `uploads/` directory (for legacy files)
  3. `literature/pdfs/` directory fallback

## Testing Recommendations

1. **PDF Preview:** Test viewing PDFs for all migrated literature entries
2. **Reparse Function:** Test reparse functionality to ensure it finds files correctly
3. **New Upload:** Upload a new PDF and verify it goes to correct location
4. **Appendix Upload:** Upload an appendix and verify naming and location

## Migration Script

The migration script `migrate_pdfs.py` is preserved for reference. It can be used as a template for future migrations.
