import { NextResponse } from 'next/server';
import { db } from '@/lib/db';
import { chunkDocument, type ParsedDocument } from '@/lib/document-parser';
import { invalidateRagIndex } from '@/lib/rag';
import { DEFAULT_SKILLS } from '@/lib/skills';

/**
 * POST /api/seed — 初始化演示数据
 * 内置 6 篇经典 Cryo-EM 文献知识 + 结构缓存 + 技能库
 */
interface SeedPaper {
  title: string;
  authors: string[];
  year: number;
  journal: string;
  doi: string;
  pdbIds: string[];
  uniprotIds: string[];
  content: string;
}

const SEED_PAPERS: SeedPaper[] = [
  {
    title: 'Cryo-EM structure of the 2019-nCoV spike in the prefusion conformation',
    authors: ['Walls AC', 'Park YJ', 'Tortorici MA', 'Wall A', 'McGuire AT', 'Veesler D'],
    year: 2020,
    journal: 'Science',
    doi: '10.1126/science.abb2507',
    pdbIds: ['6VXX', '6VYB'],
    uniprotIds: ['P0DTC2'],
    content: `The 2019 novel coronavirus (2019-nCoV) has spread rapidly worldwide. Here we present the cryo-EM structure of the 2019-nCoV spike (S) glycoprotein in the prefusion conformation at 3.5 angstrom resolution. The spike is a trimeric class I fusion protein that mediates viral entry.

The S protein comprises two subunits: S1, which contains the receptor-binding domain (RBD), and S2, which contains the fusion machinery. The RBD undergoes hinge-like conformational movements that transiently hide or expose the determinants of receptor binding. These two states are referred to as the "down" conformation and the "up" conformation. The down conformation corresponds to the receptor-inaccessible state in which the RBD is buried at the interface between neighboring protomers, whereas the up conformation corresponds to the receptor-accessible state.

Cryo-EM data collection was performed on a 300 keV Titan Krios microscope equipped with a Gatan K2 direct electron detector. A total of 3,728 micrographs were collected with a defocus range of -0.5 to -2.5 micrometers. Particles were picked automatically and 2D classification, 3D classification, and refinement were performed using RELION 3.0. The final map was reconstructed from 126,879 particles at 3.5 angstrom global resolution with a B-factor of -128 angstrom squared.

The 2019-nCoV S protein binds the human ACE2 receptor with higher affinity than the SARS-CoV S protein. Structural comparison reveals that the RBD of 2019-nCoV has a 10-fold higher affinity for ACE2. The polybasic cleavage site at the S1/S2 boundary contains 12 additional residues compared to the SARS-CoV S protein, which may facilitate additional proteolytic cleavage by furin-like proteases.

Our findings demonstrate that the 2019-nCoV S ectodomain trimer is predominantly in the closed conformation, which obscures the receptor-binding sites. Only a small fraction of trimers adopt the open conformation necessary for ACE2 binding. These structures provide a blueprint for the design of vaccines and inhibitors of viral entry.`,
  },
  {
    title: 'Structural basis for the recognition of SARS-CoV-2 by full-length human ACE2',
    authors: ['Yan R', 'Zhang Y', 'Li Y', 'Xia L', 'Guo Y', 'Zhou Q'],
    year: 2020,
    journal: 'Science',
    doi: '10.1126/science.abb2762',
    pdbIds: ['6M0J'],
    uniprotIds: ['Q9BYF1'],
    content: `The outbreak of a novel coronavirus (SARS-CoV-2) poses a serious global health threat. Here we present the cryo-EM structure of the full-length human ACE2, the receptor of SARS-CoV-2, in complex with the receptor-binding domain (RBD) of the spike protein of SARS-CoV-2 at 2.9 angstrom resolution.

Overall structure of the ACE2-B0AT1 complex. Human ACE2 forms a homodimer, and each protomer binds one B0AT1 molecule. The extracellular region of ACE2 consists of a neck domain and a peptidase domain. The RBD of SARS-CoV-2 binds to the peptidase domain of ACE2 from the outer surface.

The complex structure reveals that the RBD of SARS-CoV-2 interacts with ACE2 through extensive hydrogen bonding and hydrophobic interactions. Key residues in the receptor-binding motif (RBM) of the RBD include Lys417, Gly446, Tyr449, Tyr453, Leu455, Phe456, Tyr473, Gln474, Leu482, Tyr489, Gln493, Gly496, Gln498, Thr500, Asn501, Gly502, and Tyr503. These residues form the interface with ACE2 residues Gln24, Leu79, Met82, Tyr83, Glu329, Lys353, and Asp38 of the alpha1 helix.

Cryo-EM grids were prepared using a Vitrobot Mark IV with blotting times of 3-5 seconds. Data were collected on a 300 kV FEI Titan Krios with a Gatan K3 detector in super-resolution mode. The final reconstruction contained 118,637 particles and achieved 2.9 angstrom resolution according to the gold-standard FSC criterion of 0.143.

Structural comparison with the SARS-CoV RBD-ACE2 complex reveals higher affinity of SARS-CoV-2 RBD for ACE2, explaining the efficient human-to-human transmission of SARS-CoV-2. These structural details provide guidance for the design of antiviral therapeutics targeting the interaction interface.`,
  },
  {
    title: 'Single-particle cryo-EM at atomic resolution',
    authors: ['Nakane T', 'Kotecha A', 'Sente A', 'Patwardhan A', 'Salcedo S', 'Moriya T', 'Scheres SHW'],
    year: 2020,
    journal: 'Nature',
    doi: '10.1038/s41586-020-2425-6',
    pdbIds: [],
    uniprotIds: [],
    content: `Single-particle cryogenic electron microscopy (cryo-EM) has become a powerful method for elucidating the three-dimensional structures of biological macromolecules. Recent advances in detector technology, image processing algorithms, and computing hardware have enabled cryo-EM to reach atomic resolution.

Key methodological advances include: direct electron detectors that enable movie-mode data collection and motion correction; improved algorithms for CTF estimation, particle picking, and 2D/3D classification; and Bayesian approaches to structure refinement implemented in software such as RELION.

We present two benchmark structures: mouse apoferritin at 1.2 angstrom resolution and the COVID-19 virus polymerase complex at 2.8 angstrom resolution. The apoferritin structure allows unambiguous placement of 1,634 protein atoms, revealing detailed features such as alternative conformations of side chains, multiple states of coordinated water molecules, and hydrogen atom densities.

Data processing workflow: beam-induced motion was corrected using MotionCor2 with dose weighting. CTF parameters were estimated using CTFFIND 4.1. Particles were selected using crYOLO or Topaz. Multiple rounds of 2D and 3D classification were performed to select homogeneous particle subsets. Per-particle CTF refinement and Bayesian polishing improved the map quality significantly. The final maps were sharpened using post-processing procedures in RELION.

Resolution estimation by the gold-standard Fourier shell correlation (FSC) criterion at 0.143 has become the community standard. Local resolution estimation reveals heterogeneity within the map. Validation metrics include Q-scores for atomic model fit and Ramachandran statistics for model geometry.

The achievement of atomic resolution single-particle cryo-EM opens new possibilities for structure-based drug design, as it reveals the detailed chemical environments of ligand binding sites and enzymatic active sites.`,
  },
  {
    title: 'The cryo-EM structure of the spliceosome Activation Intermediate (Bact complex) at 6.6 angstrom',
    authors: ['Zhang X', 'Yan C', 'Hang J', 'Fung LF', 'Lei J', 'Shi Y'],
    year: 2017,
    journal: 'Science',
    doi: '10.1126/science.aak9979',
    pdbIds: ['5ILH'],
    uniprotIds: [],
    content: `The spliceosome is a dynamic molecular machine that catalyzes the removal of introns from pre-mRNA through two consecutive transesterification reactions. We present the cryo-EM structure of the activated spliceosome (Bact complex) from Saccharomyces cerevisiae at an overall resolution of 6.6 angstrom.

The Bact complex contains the U2, U5, and U6 snRNAs, nineteen protein subunits of the NineTeen Complex (NTC), and six protein components of the retention and recovery complex (RES). The catalytically essential U6 snRNA adopts an intramolecular stem-loop (ISL) conformation, and the branching duplex is poised near the catalytic center.

Structural analysis reveals that the Prp2 RNA helicase is recruited to the Bact complex through its interaction with the Brr2 helicase and Spp2. The ATPase activity of Prp2 is required for the catalytic activation of the spliceosome. The SF3a and SF3b complexes stabilize the branching point helix.

Cryo-EM specimen preparation: purified spliceosomes were applied to glow-discharged Quantifoil grids, blotted for 3 seconds, and plunge-frozen in liquid ethane. Images were recorded on a 300 kV FEI Polara or Titan Krios microscope using a K2 Summit detector in counting mode. Approximately 200,000 particles were picked; after 2D classification and 3D classification, 48,855 particles were used for the final reconstruction.

Local resolution analysis reveals that the core RNA elements, including the U6 ISL and the catalytic triplex, are well resolved at approximately 4.5 angstrom, whereas peripheral protein components exhibit lower local resolution. The structure provides mechanistic insights into the splicing cycle and the dynamic rearrangements during spliceosome activation.`,
  },
  {
    title: 'Atomic structures of a prokaryotic 70S ribosome translation intermediates by cryo-EM',
    authors: ['Fischer N', 'Neumann P', 'Bock LV', 'Maracci C', 'Wang Z', 'Stark H', 'Rodnina MV'],
    year: 2016,
    journal: 'Nature',
    doi: '10.1038/nature16988',
    pdbIds: [],
    uniprotIds: [],
    content: `Protein synthesis by the ribosome is a fundamental process in all living cells. We present a series of cryo-EM structures of the Escherichia coli 70S ribosome captured at different states of elongation factor Tu (EF-Tu)-dependent decoding at resolutions of 2.9-3.4 angstrom.

During decoding, aminoacyl-tRNA in complex with EF-Tu and GTP enters the A site of the ribosome. Initial selection involves codon-anticodon pairing in the decoding center of the small subunit. GTP hydrolysis by EF-Tu is accelerated by the catalytic histidine (His84) upon correct codon-anticodon recognition. The subsequent conformational changes lead to tRNA accommodation into the peptidyl transferase center.

The cryo-EM structures reveal the trajectory of tRNA from the A/T state to the A/A state, including the pivotal role of the sarcin-ricin loop (SRL) of the 23S rRNA in GTPase activation. The decoding center undergoes a rearrangement from an open to a closed conformation upon cognate codon recognition, involving residues A1492, A1493, and G530 of the 16S rRNA.

Cryo-EM methodology: ribosome complexes were vitrified on holey carbon grids. Data were collected using a Titan Krios microscope at 300 kV with a K2 Summit direct detector. Movies of 20 frames were recorded with an exposure of 1.5 electrons per angstrom squared per frame. Particle picking yielded 1.2 million particles; 3D classification separated the different functional states. Final maps were refined using focused classification with signal subtraction.

These structures, together with kinetic data, provide a near-atomic-level view of the molecular choreography of protein synthesis and explain the fidelity of translation at the molecular level.`,
  },
  {
    title: 'AlphaFold protein structure prediction method achieves atomic-level accuracy',
    authors: ['Jumper J', 'Evans R', 'Pritzel A', 'Green T', 'Figurnov M', 'Tunyasuvunakool K', 'Hassabis D'],
    year: 2021,
    journal: 'Nature',
    doi: '10.1038/s41586-021-03819-2',
    pdbIds: [],
    uniprotIds: [],
    content: `Predicting the three-dimensional structure of a protein from its amino acid sequence remains one of the grand challenges in biology. We present AlphaFold, a neural network-based method that achieves accuracy competitive with experimental structures in the majority of cases.

The AlphaFold network directly predicts the 3D coordinates of all heavy atoms from the amino acid sequence. The architecture consists of two main stages: (1) an attention-based neural network module (Evoformer) that processes sequence and alignment information, and (2) a structure module that converts the representations into 3D structure using invariant point attention.

The Evoformer processes multiple sequence alignments (MSAs) and pair representations through 48 blocks of alternating row-wise and column-wise attention. The pair representation encodes the relationship between every pair of residues, enabling direct modeling of residue-residue geometric constraints.

In the 14th Critical Assessment of protein Structure Prediction (CASP14), AlphaFold achieved a median backbone accuracy of 0.96 angstrom root-mean-square deviation (RMSD95) and a median all-atom accuracy of 1.5 angstrom for the submitted targets. This performance is comparable to the agreement between experimental structures determined by X-ray crystallography at approximately 1.5 angstrom resolution.

The method demonstrates particular strength in modeling protein side chains, backbone irregularity, and domain packing. Limitations remain in predicting the structure of intrinsically disordered regions, multiple conformational states, and protein-ligand interactions.

The predicted structures and confidence estimates enable broad applications in structural biology research, including cryo-EM model building, crystallographic molecular replacement, and the annotation of protein function. The AlphaFold Protein Structure Database provides open access to predicted structures for over 200 million proteins.`,
  },
];

export async function POST() {
  try {
    const litCount = await db.literature.count();
    if (litCount > 0) {
      return NextResponse.json({ success: true, alreadySeeded: true, literatureCount: litCount });
    }

    // 1. 技能库
    const skillCount = await db.skill.count();
    if (skillCount === 0) {
      await db.skill.createMany({
        data: DEFAULT_SKILLS.map((s) => ({
          id: s.id,
          name: s.name,
          description: s.description,
          category: s.category,
          triggerKeywords: JSON.stringify(s.triggerKeywords),
          systemPrompt: s.systemPrompt,
          tools: JSON.stringify(s.tools),
          steps: JSON.stringify(s.steps),
          examples: JSON.stringify(s.examples),
          parameters: JSON.stringify(s.parameters),
          isBuiltin: true,
        })),
      });
    }

    // 2. 文献 + 分块
    let totalChunks = 0;
    for (const paper of SEED_PAPERS) {
      const doc: ParsedDocument = {
        fullText: paper.content,
        sections: chunkSections(paper.content),
        wordCount: paper.content.split(/\s+/).length,
        pageCount: 3,
        metadata: {
          title: paper.title,
          authors: paper.authors,
          doi: paper.doi,
          year: paper.year,
        },
      };
      const chunks = chunkDocument(doc);
      const lit = await db.literature.create({
        data: {
          title: paper.title,
          authors: JSON.stringify(paper.authors),
          year: paper.year,
          journal: paper.journal,
          doi: paper.doi,
          abstract: paper.content.slice(0, 800),
          parseStatus: 'parsed',
          chunkCount: chunks.length,
          wordCount: doc.wordCount,
          keywords: 'Cryo-EM, structural biology',
        },
      });
      if (chunks.length > 0) {
        await db.literatureChunk.createMany({
          data: chunks.map((c) => ({
            literatureId: lit.id,
            chunkIndex: c.chunkIndex,
            section: c.section,
            page: null,
            content: c.content,
            wordCount: c.wordCount,
          })),
        });
      }
      totalChunks += chunks.length;

      // 3. 结构关联
      for (const pdbId of paper.pdbIds) {
        await db.structure.upsert({
          where: { id: pdbId },
          create: { id: pdbId, title: `${pdbId} — ${paper.title.slice(0, 60)}`, source: 'seed' },
          update: {},
        });
        await db.structureLink.upsert({
          where: { literatureId_structureId: { literatureId: lit.id, structureId: pdbId } },
          create: { literatureId: lit.id, structureId: pdbId, mentionCount: 1 },
          update: { mentionCount: { increment: 1 } },
        });
      }
    }

    // 4. 热门结构缓存 (著名结构)
    const popularStructures = [
      { id: '6M17', title: 'SARS-CoV-2 spike and human ACE2 complex (Tang et al. 2020)' },
      { id: '7A4N', title: 'SARS-CoV-2 RNA polymerase complex (Hillen et al. 2020)' },
      { id: '7KDX', title: 'SARS-CoV-2 spike immunogen complex' },
    ];
    for (const s of popularStructures) {
      await db.structure.upsert({
        where: { id: s.id },
        create: { id: s.id, title: s.title, source: 'seed' },
        update: { title: s.title },
      });
    }

    invalidateRagIndex();

    return NextResponse.json({
      success: true,
      seeded: {
        literature: SEED_PAPERS.length,
        chunks: totalChunks,
        skills: DEFAULT_SKILLS.length,
        structures: new Set(SEED_PAPERS.flatMap((p) => p.pdbIds).concat(popularStructures.map((p) => p.id))).size,
      },
    });
  } catch (err) {
    return NextResponse.json({ error: err instanceof Error ? err.message : '初始化失败' }, { status: 500 });
  }
}

/** 简化版章节识别 (供 seed 使用) */
function chunkSections(content: string) {
  const paragraphs = content.split('\n\n');
  return paragraphs.map((p, i) => ({
    section: i === 0 ? 'abstract' : i < 2 ? 'intro' : 'body',
    page: null,
    content: p,
  }));
}

export async function GET() {
  const [lit, chunks, skills, structures, links] = await Promise.all([
    db.literature.count(),
    db.literatureChunk.count(),
    db.skill.count(),
    db.structure.count(),
    db.structureLink.count(),
  ]);
  return NextResponse.json({
    counts: { literature: lit, chunks, skills, structures, links },
    needsSeed: lit === 0,
  });
}
