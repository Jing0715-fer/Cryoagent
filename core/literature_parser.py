# literature_parser.py - CryoAgent Pro 文献解析模块（支持RAG优化版，修复章节提取和元数据优先级）
import os, json, re, logging, hashlib, tempfile
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple, Union
from datetime import datetime
import time
import subprocess

# PDF转换超时时间（秒）- 用于限制处理时间
PDF_CONVERT_TIMEOUT = 60  # 60秒超时

# 尝试导入 pdfplumber（可选）
try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False
    print("⚠️ pdfplumber未安装，部分功能受限")

import pymupdf  # PyMuPDF (fitz)

# 导入extract_structure_ids.py所需的库
from io import BytesIO, StringIO
from bs4 import BeautifulSoup
try:
    from pdfminer.converter import HTMLConverter, TextConverter
    from pdfminer.layout import LAParams
    from pdfminer.pdfinterp import PDFResourceManager, PDFPageInterpreter
    from pdfminer.pdfpage import PDFPage
    HAS_PDFMINER = True
except ImportError:
    HAS_PDFMINER = False
    print("⚠️ pdfminer未安装，部分PDF转换功能受限")

# 尝试多种 PDF 库导入方式
try:
    import PyPDF2 as pypdf2
    HAS_PYPDF2 = True
except ImportError:
    try:
        import pypdf2
        HAS_PYPDF2 = True
    except ImportError:
        HAS_PYPDF2 = False
        print("⚠️ PyPDF2 未安装，部分PDF元数据提取功能受限")

try:
    import bibtexparser
    HAS_BIBTEX = True
except ImportError:
    HAS_BIBTEX = False
    print("⚠️ bibtexparser 未安装，BibTeX导入功能受限")

try:
    import scholarly
    HAS_SCHOLARLY = True
except ImportError:
    HAS_SCHOLARLY = False
    print("⚠️ scholarly 未安装，在线元数据获取功能受限")

# 导入新的AI解析函数
try:
    from core.agent_core import parse_text_with_llm, ask_literature_question, HAS_AGENT
except ImportError:
    HAS_AGENT = False
    print("⚠️ agent_core 未导入，AI解析功能受限")

# 导入StructureMetadataFetcher用于应用层过滤
try:
    from core.structure_manager import StructureMetadataFetcher
    HAS_STRUCTURE_MANAGER = True
except ImportError:
    HAS_STRUCTURE_MANAGER = False
    print("⚠️ structure_manager 未导入，应用层过滤功能受限")

# 导入RCSB PDB搜索API（用于DOI到PDB ID的转换）
try:
    from core.structure_extractor_fixed import RCSBPDBSearch
    HAS_RCSB_SEARCH = True
except ImportError:
    HAS_RCSB_SEARCH = False
    print("⚠️ structure_extractor_fixed 未导入，DOI到PDB ID功能受限")

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ---------- 配置文件 ----------
class LiteratureParserConfig:
    """文献解析配置"""
    
    # PDF解析配置
    PDF_EXTRACT_IMAGES = True  # 是否提取图像
    PDF_EXTRACT_TABLES = True  # 是否提取表格
    PDF_MAX_PAGES = 100  # 最大解析页数
    PDF_TEXT_CHUNK_SIZE = 2000  # 文本分块大小
    
    # AI解析配置
    AI_ENABLED = HAS_AGENT  # 根据实际导入情况决定
    AI_MAX_TOKENS = 8000  # AI处理最大token数
    AI_EXTRACT_METADATA = True  # AI提取元数据
    AI_EXTRACT_KEY_FINDINGS = True  # AI提取关键发现
    AI_GENERATE_SUMMARY = True  # AI生成摘要
    
    # 网络检索配置
    FETCH_METADATA_ONLINE = True  # 是否在线获取元数据
    ONLINE_SOURCES = ["crossref", "arxiv", "pubmed"]  # 在线数据源优先级
    
    # 元数据优先级配置（新增）
    METADATA_PRIORITY_ORDER = ["online", "ai", "pdf"]  # 元数据优先级：在线 > AI > PDF
    
    # 性能配置
    MAX_WORKERS = min(4, os.cpu_count() or 2)  # 根据CPU核心数调整
    TIMEOUT_SECONDS = 30  # 超时时间（秒）
    
    # 结构ID提取配置
    EXTRACT_STRUCTURE_IDS = True  # 是否提取结构ID
    PREFER_DATA_AVAILABILITY_SECTION = True  # 优先从数据可用性部分提取
    
    # 章节解析配置（新增）
    USE_HTML_FOR_SECTION_PARSING = True  # 优先使用HTML进行章节识别
    MIN_SECTION_LENGTH = 50  # 最小章节长度
    MAX_SECTION_LENGTH = 10000  # 最大章节长度
    
    # RAG配置（新增）
    GENERATE_EMBEDDINGS = False  # 是否生成向量嵌入（默认关闭，需要额外处理）
    EMBEDDING_MODEL = "text-embedding-3-small"  # 默认嵌入模型
    EMBEDDING_DIMENSIONS = 1536  # 嵌入维度
    
    # 章节识别阈值（新增）
    SECTION_CONFIDENCE_THRESHOLD = 0.7  # 章节识别置信度阈值
    
    # 在线元数据配置（新增）
    ONLINE_METADATA_FALLBACK = True  # 在线元数据失败后是否使用本地解析
    SAVE_FULL_ONLINE_METADATA = True  # 保存完整的在线元数据

# ---------- 结构ID提取器 ----------
class StructureIDExtractor:
    """结构ID提取器（PDB和EMDB）- 严格按照extract_structure_ids.py标准实现"""
    
    def __init__(self, config: LiteratureParserConfig = None):
        self.config = config or LiteratureParserConfig()
        
        # 简化的PDB ID模式（与extract_structure_ids.py完全一致）
        self.pdb_patterns = [
            # 匹配标准PDB ID格式（4个字符，第一位是数字，后三位是字母数字）
            r'\b([1-9][A-Za-z0-9]{3})\b',
            # 从URL中提取PDB ID
            r'structure/(?:unreleased/)?([1-9][A-Za-z0-9]{3})',
            r'rcsb\.org/structure/(?:unreleased/)?([1-9][A-Za-z0-9]{3})',
        ]
        
        # 数据可用性部分的关键词（与extract_structure_ids.py完全一致）
        self.availability_keywords = [
            'data availability',
            'data and materials availability',
            'data and code availability',
            'structural data',
            'accession codes',
            'pdb id',
            'emdb id',
            'deposition',
            'coordinates deposited',
            'protein data bank',
            'electron microscopy data bank',
            'data availability statement',
            'availability statement',
            'data deposition'
        ]
    
    def convert_pdf_to_html_pdfminer(self, pdf_path):
        """使用pdfminer将PDF转换为HTML（与extract_structure_ids.py完全一致），带超时保护"""
        if not HAS_PDFMINER:
            logger.warning("pdfminer未安装，无法使用此方法")
            return None

        # 检查文件大小，对于超大文件直接跳过
        file_size = os.path.getsize(pdf_path)
        if file_size > 10 * 1024 * 1024:  # 超过10MB直接跳过HTML转换，避免卡住
            logger.warning(f"PDF文件较大 ({file_size / 1024 / 1024:.1f}MB)，跳过HTML转换以避免处理超时")
            return None

        # 检查页数，页数过多则跳过
        try:
            with open(pdf_path, 'rb') as f:
                page_count = sum(1 for _ in PDFPage.get_pages(f))
            if page_count > 500:
                logger.warning(f"PDF页数过多 ({page_count}页)，跳过HTML转换以避免超时")
                return None
        except:
            pass

        try:
            # 创建字节缓冲区
            output_bytes = BytesIO()

            # 创建PDF资源管理器
            resource_manager = PDFResourceManager()

            # 创建HTML转换器
            converter = HTMLConverter(
                resource_manager,
                output_bytes,
                laparams=LAParams(),
                imagewriter=None
            )

            # 创建PDF页面解释器
            interpreter = PDFPageInterpreter(resource_manager, converter)

            # 打开PDF文件
            with open(pdf_path, 'rb') as file:
                # 逐页处理
                page_count = 0
                start_time = time.time()
                for page in PDFPage.get_pages(file, caching=True, check_extractable=True):
                    interpreter.process_page(page)
                    page_count += 1
                    # 每处理20页检查一次耗时
                    if page_count % 20 == 0:
                        elapsed = time.time() - start_time
                        if elapsed > PDF_CONVERT_TIMEOUT:
                            logger.warning(f"PDF转HTML超时 ({elapsed:.1f}秒)，跳过剩余页面")
                            break
                        logger.info(f"已处理 {page_count} 页...")

            # 关闭转换器
            converter.close()

            # 获取HTML内容
            html_content = output_bytes.getvalue().decode('utf-8', errors='ignore')
            output_bytes.close()

            if html_content and len(html_content) > 100:
                return html_content
            return None

        except Exception as e:
            logger.warning(f"PDF转HTML时出错 (pdfminer): {e}")
            return None
    
    def convert_pdf_to_text_pdfminer(self, pdf_path):
        """使用pdfminer将PDF转换为纯文本（与extract_structure_ids.py完全一致），带超时保护"""
        if not HAS_PDFMINER:
            logger.warning("pdfminer未安装，无法使用此方法")
            return None

        # 检查文件大小，对于超大文件直接跳过
        file_size = os.path.getsize(pdf_path)
        if file_size > 50 * 1024 * 1024:  # 超过50MB直接跳过
            logger.warning(f"PDF文件过大 ({file_size / 1024 / 1024:.1f}MB)，跳过文本转换")
            return None

        # 检查页数，页数过多则跳过
        try:
            with open(pdf_path, 'rb') as f:
                page_count = sum(1 for _ in PDFPage.get_pages(f))
            if page_count > 500:
                logger.warning(f"PDF页数过多 ({page_count}页)，跳过文本转换以避免超时")
                return None
        except:
            pass

        try:
            # 创建字符串缓冲区
            output_string = StringIO()

            # 创建PDF资源管理器
            resource_manager = PDFResourceManager()

            # 创建文本转换器
            converter = TextConverter(
                resource_manager,
                output_string,
                laparams=LAParams()
            )

            # 创建PDF页面解释器
            interpreter = PDFPageInterpreter(resource_manager, converter)

            # 打开PDF文件
            with open(pdf_path, 'rb') as file:
                # 逐页处理
                page_count = 0
                start_time = time.time()
                for page in PDFPage.get_pages(file, caching=True, check_extractable=True):
                    interpreter.process_page(page)
                    page_count += 1
                    # 每处理20页检查一次耗时
                    if page_count % 20 == 0:
                        elapsed = time.time() - start_time
                        if elapsed > PDF_CONVERT_TIMEOUT:
                            logger.warning(f"PDF转文本超时 ({elapsed:.1f}秒)，跳过剩余页面")
                            break

            # 关闭转换器
            converter.close()

            # 获取文本内容
            text_content = output_string.getvalue()
            output_string.close()

            return text_content

        except Exception as e:
            logger.warning(f"PDF转文本时出错 (pdfminer): {e}")
            return None
    
    def convert_pdf_to_html_pdftohtml(self, pdf_path):
        """使用pdftohtml命令行工具将PDF转换为HTML（如果有安装）（与extract_structure_ids.py完全一致）"""
        try:
            # 检查是否安装了pdftohtml
            result = subprocess.run(['which', 'pdftohtml'], capture_output=True, text=True)
            if result.returncode != 0:
                logger.warning("pdftohtml未安装，跳过此方法")
                return None
            
            # 创建临时目录
            with tempfile.TemporaryDirectory() as tmpdir:
                # 构建输出文件路径
                output_base = os.path.join(tmpdir, 'output')
                
                # 运行pdftohtml命令
                cmd = ['pdftohtml', '-stdout', '-noframes', pdf_path]
                result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore')
                
                if result.returncode == 0:
                    return result.stdout
                else:
                    logger.warning(f"pdftohtml命令失败: {result.stderr}")
                    return None
                    
        except Exception as e:
            logger.warning(f"PDF转HTML时出错 (pdftohtml): {e}")
            return None
    
    def convert_pdf_to_text_pdftotext(self, pdf_path):
        """使用pdftotext命令行工具将PDF转换为文本（如果有安装）（与extract_structure_ids.py完全一致）"""
        try:
            # 检查是否安装了pdftotext
            result = subprocess.run(['which', 'pdftotext'], capture_output=True, text=True)
            if result.returncode != 0:
                logger.warning("pdftotext未安装，跳过此方法")
                return None
            
            # 运行pdftotext命令
                cmd = ['pdftotext', '-layout', pdf_path, '-']
                result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore')
                
                if result.returncode == 0:
                    return result.stdout
                else:
                    logger.warning(f"pdftotext命令失败: {result.stderr}")
                    return None
                        
        except Exception as e:
            logger.warning(f"PDF转文本时出错 (pdftotext): {e}")
            return None
    
    def convert_pdf_to_html(self, pdf_path):
        """将PDF转换为HTML，尝试多种方法（与extract_structure_ids.py完全一致）"""
        logger.info("开始将PDF转换为HTML...")
        
        # 首先尝试pdfminer
        html_content = self.convert_pdf_to_html_pdfminer(pdf_path)
        
        # 如果失败，尝试pdftohtml
        if not html_content:
            logger.info("pdfminer转换失败，尝试pdftohtml...")
            html_content = self.convert_pdf_to_html_pdftohtml(pdf_path)
        
        if html_content:
            logger.info(f"PDF转换成功，HTML大小: {len(html_content)} 字符")
        else:
            logger.warning("PDF转换失败")
            
        return html_content
    
    def convert_pdf_to_text(self, pdf_path):
        """将PDF转换为文本，尝试多种方法（与extract_structure_ids.py完全一致）"""
        logger.info("开始将PDF转换为文本...")
        
        # 首先尝试pdfminer
        text_content = self.convert_pdf_to_text_pdfminer(pdf_path)
        
        # 如果失败，尝试pdftotext
        if not text_content:
            logger.info("pdfminer转换失败，尝试pdftotext...")
            text_content = self.convert_pdf_to_text_pdftotext(pdf_path)
        
        if text_content:
            logger.info(f"PDF转换成功，文本大小: {len(text_content)} 字符")
        else:
            logger.warning("PDF转换失败")
            
        return text_content
    
    def extract_data_availability_from_html(self, html_content):
        """从HTML中提取Data Availability部分（与extract_structure_ids.py完全一致）"""
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # 方法1: 查找包含关键词的文本节点，并获取其父元素
            data_sections = []
            
            # 查找所有文本节点
            for text_node in soup.find_all(string=True):
                if text_node.parent.name in ['script', 'style', 'meta', 'link']:
                    continue
                    
                text = str(text_node).strip()
                if not text:
                    continue
                
                # 检查是否包含关键词
                for keyword in self.availability_keywords:
                    if keyword in text.lower():
                        # 获取包含此文本的父元素
                        parent = text_node.parent
                        
                        # 向上查找，直到找到包含完整段落的元素
                        # 我们尝试获取整个section或div的内容
                        while parent and parent.name not in ['body', 'html']:
                            # 检查父元素是否包含足够的文本
                            parent_text = parent.get_text(separator=' ', strip=True)
                            if len(parent_text) > 100:  # 足够长的文本块
                                # 获取该元素及其后续兄弟元素的内容
                                section_content = self._extract_element_and_following_siblings(parent)
                                if section_content and section_content not in data_sections:
                                    data_sections.append(section_content)
                                break
                            parent = parent.parent
            
            # 方法2: 查找标题元素（如h1, h2, h3等）包含关键词的情况
            heading_tags = ['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'strong', 'b']
            for tag in heading_tags:
                for heading in soup.find_all(tag):
                    heading_text = heading.get_text(strip=True).lower()
                    for keyword in self.availability_keywords:
                        if keyword in heading_text:
                            # 获取标题后的内容
                            section_content = self._extract_content_after_heading(heading)
                            if section_content and section_content not in data_sections:
                                data_sections.append(section_content)
            
            # 方法3: 查找段落包含关键词的情况
            for paragraph in soup.find_all(['p', 'div']):
                paragraph_text = paragraph.get_text(strip=True).lower()
                for keyword in self.availability_keywords:
                    if keyword in paragraph_text:
                        full_text = paragraph.get_text(separator=' ', strip=True)
                        if full_text and full_text not in data_sections:
                            data_sections.append(full_text)
            
            # 合并所有找到的部分
            if data_sections:
                # 去重
                unique_sections = []
                seen = set()
                for section in data_sections:
                    # 取前200个字符作为标识
                    section_id = section[:200]
                    if section_id not in seen:
                        seen.add(section_id)
                        unique_sections.append(section)
                
                # 合并所有部分
                merged_section = "\n\n".join(unique_sections)
                
                # 截取合理长度（Data Availability部分通常不会太长）
                # 我们取包含关键词的前后各1000个字符
                merged_lower = merged_section.lower()
                for keyword in self.availability_keywords:
                    if keyword in merged_lower:
                        pos = merged_lower.find(keyword)
                        start = max(0, pos - 1000)
                        end = min(len(merged_section), pos + 5000)  # Data部分可能较长
                        extracted = merged_section[start:end]
                        
                        # 确保提取的部分包含完整的句子
                        # 向前找到句号或开头
                        for i in range(start, max(0, start-200), -1):
                            if i == 0 or merged_section[i-1] in '.!?':
                                start = i
                                break
                        
                        # 向后找到句号或结尾
                        for i in range(end, min(len(merged_section), end+200)):
                            if i == len(merged_section)-1 or merged_section[i] in '.!?':
                                end = i+1
                                break
                        
                        final_section = merged_section[start:end]
                        logger.info(f"找到Data Availability部分，大小: {len(final_section)} 字符")
                        return final_section
            
            return None
            
        except Exception as e:
            logger.error(f"从HTML提取Data Availability部分时出错: {e}")
            return None
    
    def extract_data_availability_from_text(self, text_content):
        """从文本中提取Data Availability部分（与extract_structure_ids.py完全一致）"""
        try:
            logger.info("尝试从文本中提取Data Availability部分...")
            
            # 将文本按行分割
            lines = text_content.split('\n')
            data_sections = []
            
            # 查找包含关键词的行
            for i, line in enumerate(lines):
                line_lower = line.lower()
                for keyword in self.availability_keywords:
                    if keyword in line_lower:
                        # 提取该行及其后续行作为候选部分
                        section_lines = []
                        
                        # 从当前行开始，最多取20行
                        for j in range(i, min(len(lines), i + 20)):
                            section_lines.append(lines[j])
                            # 如果遇到空行或新章节，停止
                            if j > i and (lines[j].strip() == '' or 
                                         (len(lines[j]) > 0 and lines[j][0].isupper() and 
                                          lines[j].endswith(':'))):
                                break
                        
                        section_text = '\n'.join(section_lines)
                        if section_text and section_text not in data_sections:
                            data_sections.append(section_text)
            
            # 如果找到了多个候选部分，选择最可能的一个
            if data_sections:
                # 优先选择包含更多关键词的部分
                best_section = None
                best_score = 0
                
                for section in data_sections:
                    score = 0
                    section_lower = section.lower()
                    
                    # 计算关键词出现次数
                    for keyword in self.availability_keywords:
                        if keyword in section_lower:
                            score += 1
                    
                    # 额外加分如果包含"PDB"或"EMDB"
                    if 'pdb' in section_lower:
                        score += 2
                    if 'emdb' in section_lower:
                        score += 2
                    
                    if score > best_score:
                        best_score = score
                        best_section = section
                
                if best_section:
                    logger.info(f"从文本中找到Data Availability部分，大小: {len(best_section)} 字符")
                    return best_section
            
            # 如果没有找到，尝试查找文本中的"DATA AVAILABILITY"标题
            # 查找大写标题
            for i, line in enumerate(lines):
                line_stripped = line.strip()
                if (line_stripped.upper() in ['DATA AVAILABILITY', 'DATA AVAILABILITY STATEMENT', 
                                             'DATA AND MATERIALS AVAILABILITY'] or
                    any(keyword.upper() in line_stripped.upper() for keyword in self.availability_keywords)):
                    
                    # 提取标题后的内容
                    section_lines = [line_stripped]
                    for j in range(i + 1, min(len(lines), i + 30)):
                        section_lines.append(lines[j])
                        # 如果遇到新的章节标题（大写或包含冒号），停止
                        if j > i + 5 and len(lines[j].strip()) > 0:
                            next_line = lines[j].strip()
                            if (next_line.upper() == next_line and len(next_line.split()) < 5) or \
                               next_line.endswith(':'):
                                break
                    
                    section_text = '\n'.join(section_lines)
                    if section_text:
                        logger.info(f"从文本标题找到Data Availability部分，大小: {len(section_text)} 字符")
                        return section_text
            
            # 如果还是没找到，返回整个文本的一部分（通常是末尾部分，因为Data Availability通常在文章末尾）
            if len(text_content) > 5000:
                # 取最后5000个字符
                last_part = text_content[-5000:]
                logger.info(f"无法定位Data Availability部分，将使用文本末尾部分，大小: {len(last_part)} 字符")
                return last_part
            
            logger.warning("无法从文本中提取Data Availability部分")
            return None
            
        except Exception as e:
            logger.error(f"从文本提取Data Availability部分时出错: {e}")
            return None
    
    def _extract_element_and_following_siblings(self, element):
        """提取元素及其后续兄弟元素的内容（与extract_structure_ids.py完全一致）"""
        content_parts = []
        
        # 从当前元素开始
        current = element
        max_elements = 20  # 限制最多提取20个元素
        
        count = 0
        while current and count < max_elements:
            text = current.get_text(separator=' ', strip=True)
            if text:
                content_parts.append(text)
            
            # 移动到下一个兄弟元素
            current = current.find_next_sibling()
            count += 1
        
        return ' '.join(content_parts)
    
    def _extract_content_after_heading(self, heading):
        """提取标题后的内容（与extract_structure_ids.py完全一致）"""
        content_parts = []
        
        # 添加标题本身
        content_parts.append(heading.get_text(strip=True))
        
        # 获取标题后的所有兄弟元素，直到下一个标题或达到限制
        current = heading.find_next_sibling()
        max_elements = 15  # 限制最多提取15个元素
        
        count = 0
        while current and count < max_elements:
            # 如果是新的标题，停止
            if current.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                break
            
            text = current.get_text(separator=' ', strip=True)
            if text:
                content_parts.append(text)
            
            current = current.find_next_sibling()
            count += 1
        
        return ' '.join(content_parts)
    
    def extract_pdb_ids(self, text):
        """从文本中提取PDB IDs，简化匹配逻辑（与extract_structure_ids.py完全一致）"""
        pdb_ids = []
        contexts = []
        seen_ids = set()
        
        # 查找标准PDB ID（移除9MDx特定匹配）
        pattern_std = r'\b([1-9][A-Za-z0-9]{3})\b'
        for match in re.finditer(pattern_std, text, re.IGNORECASE):
            pdb_id = match.group(1).upper()
            
            # 过滤掉纯数字的ID（通常是年份）
            if pdb_id.isdigit():
                continue
                
            # 检查是否包含至少一个字母
            if not any(c.isalpha() for c in pdb_id):
                continue
            
            # 添加到列表（去重）
            if pdb_id not in seen_ids:
                seen_ids.add(pdb_id)
                pdb_ids.append(pdb_id)
                
                # 提取上下文
                start = max(0, match.start() - 100)
                end = min(len(text), match.end() + 100)
                context = text[start:end]
                contexts.append((pdb_id, context))
        
        return pdb_ids, contexts
    
    def filter_pdb_ids_by_first_digit(self, pdb_ids, contexts, emdb_ids=None, emdb_contexts=None):
        """
        根据首位数字进行初步过滤
        规则：只保留首位数字 >= 最大首位数字 - 1 的PDB ID
        
        Args:
            pdb_ids: 需要过滤的PDB ID列表
            contexts: 对应的上下文列表
            emdb_ids: EMDB ID列表（可选）
            emdb_contexts: EMDB上下文列表（可选）
            
        Returns:
            filtered_pdb_ids: 过滤后的PDB ID列表
            filtered_contexts: 过滤后的上下文列表
        """
        if not pdb_ids or not contexts:
            return pdb_ids, contexts
        
        logger.info(f"过滤前PDB IDs: {pdb_ids}")
        
        # 将contexts从元组列表转换为字典以便查找
        context_dict = {pdb_id: context for pdb_id, context in contexts}
        
        # 获取每个PDB ID的第一位数字
        first_digits = []
        valid_pdb_ids = []
        
        for pdb_id in pdb_ids:
            if pdb_id and pdb_id[0].isdigit():
                first_digits.append(int(pdb_id[0]))
                valid_pdb_ids.append(pdb_id)
            else:
                # 如果第一位不是数字，跳过
                continue
        
        if not valid_pdb_ids:
            return [], []
        
        # 找到最大的第一位数字
        max_first_digit = max(first_digits)
        
        logger.info(f"最大首位数字: {max_first_digit}")
        
        # 第一步：过滤掉首位数字比最大值小2或更多的PDB ID
        # 只保留首位数字 >= 最大首位数字 - 1 的ID
        prelim_filtered_pdb_ids = []
        prelim_filtered_digits = []
        
        for pdb_id, first_digit in zip(valid_pdb_ids, first_digits):
            if first_digit >= max_first_digit - 1:
                prelim_filtered_pdb_ids.append(pdb_id)
                prelim_filtered_digits.append(first_digit)
        
        logger.info(f"基于首位数字初步过滤后PDB IDs: {prelim_filtered_pdb_ids}")
        
        # 重新构建contexts列表
        prelim_filtered_contexts = [
            (pdb_id, context_dict[pdb_id]) for pdb_id in prelim_filtered_pdb_ids 
            if pdb_id in context_dict
        ]
        
        return prelim_filtered_pdb_ids, prelim_filtered_contexts
    
    def extract_emdb_ids(self, text):
        """从文本中提取EMDB IDs，支持多种格式，按数字部分去重（与extract_structure_ids.py完全一致）"""
        # 用于存储提取到的EMDB ID数字部分
        emdb_numbers = set()
        # 存储数字到标准格式ID的映射（数字->标准格式ID）
        emdb_id_map = {}
        # 存储数字到上下文的映射（数字->上下文）
        emdb_contexts = {}
        
        # 所有可能的EMDB ID模式，改进版
        emdb_patterns = [
            # 标准格式: EMD-XXXX, EMD_XXXX, EMDB-XXXX
            r'EMD[BD]?[-\s_]*\d{4,6}\b',
            # 带空格的格式: emd- 48166, emd -48166, emd - 48166
            r'EMD[\s]*-?[\s]*\d{4,6}\b',
            # 带有冒号的格式: EMD: 12345, EMDB: 12345
            r'EMD[BD]?[\s_:]+\d{4,6}\b',
            # 完整名称格式: Electron Microscope Data Bank 12345
            r'Electron Microscope[\s\w]*Data Bank[\s_:]*\d{4,6}\b',
            # 多个ID用斜杠分隔: EMD-12037/12038/12041/12048/12050
            r'EMD[-\s]*\d{4,6}(?:[/,_\s]+\d{4,6})+\b',
            # 多个ID用逗号分隔: EMD-60428, EMD-60429
            r'EMD[-\s]*\d{4,6}(?:,\s*EMD[-\s]*\d{4,6})+\b',
            # 从URL中提取EMDB ID，如 www.ebi.ac.uk/emdb/EMD-48169
            r'ebi\.ac\.uk/emdb/(EMD[-\s_]*\d{4,6})\b',
            r'emdb/(EMD[-\s_]*\d{4,6})\b',
        ]
        
        # 特别处理连续无空格的文本
        # 例如：EMD-60428(C1),EMD-60429(C1a)
        continuous_patterns = [
            r'EMD-(\d{5})(?:\([^)]+\))?(?:,EMD-(\d{5})(?:\([^)]+\))?)*',
            r'EMDB-(\d{5})(?:\([^)]+\))?(?:,EMDB-(\d{5})(?:\([^)]+\))?)*',
        ]
        
        for pattern in continuous_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                # 获取所有匹配的数字
                for i in range(1, len(match.groups()) + 1):
                    num = match.group(i)
                    if num and num.isdigit():
                        num_int = int(num)
                        if num_int not in emdb_numbers:
                            emdb_numbers.add(num_int)
                            emdb_id = f"EMD-{num}"
                            emdb_id_map[num_int] = emdb_id
                            
                            # 提取上下文
                            start = max(0, match.start() - 100)
                            end = min(len(text), match.end() + 100)
                            context = text[start:end]
                            emdb_contexts[num_int] = context
        
        for pattern in emdb_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                matched_text = match.group()
                
                # 从匹配的文本中提取所有4-6位数字
                numbers = re.findall(r'\d{4,6}', matched_text)
                
                # 处理提取到的数字
                for num in numbers:
                    num_int = int(num)
                    # 添加到集合中（自动去重）
                    if num_int not in emdb_numbers:
                        emdb_numbers.add(num_int)
                        # 创建标准格式的ID
                        emdb_id = f"EMD-{num}"
                        emdb_id_map[num_int] = emdb_id
                        
                        # 提取上下文
                        start = max(0, match.start() - 100)
                        end = min(len(text), match.end() + 100)
                        context = text[start:end]
                        emdb_contexts[num_int] = context
        
        # 转换为排序后的列表
        sorted_numbers = sorted(emdb_numbers)
        emdb_ids = [emdb_id_map[num] for num in sorted_numbers]
        contexts = [emdb_contexts[num] for num in sorted_numbers]
        
        # 创建(emdb_id, context)的元组列表
        emdb_context_tuples = [(emdb_ids[i], contexts[i]) for i in range(len(emdb_ids))]
        
        return emdb_ids, emdb_context_tuples
    
    def process_pdf_extract_ids(self, pdf_path, pre_extracted_html=None, pre_extracted_sections=None):
        """处理PDF文件并提取结构ID（严格按照extract_structure_ids.py流程）

        Args:
            pdf_path: PDF文件路径
            pre_extracted_html: 预先提取的HTML内容（避免重复转换）
            pre_extracted_sections: 预先提取的章节数据（可能包含data_availability）
        """
        logger.info(f"处理文件: {pdf_path}")

        data_availability_section = None
        source_type = None

        # 1. 优先使用预先提取的章节数据中的data_availability
        if pre_extracted_sections and pre_extracted_sections.get("data_availability"):
            data_availability_section = pre_extracted_sections.get("data_availability", "")
            if data_availability_section:
                source_type = "章节数据"
                logger.info("从预提取的章节数据中获取Data Availability部分")

        # 2. 如果没有预提取数据，尝试将PDF转换为HTML并提取Data Availability部分
        html_content = None
        if not data_availability_section:
            logger.info("方法1: 尝试HTML转换...")
            html_content = pre_extracted_html if pre_extracted_html else self.convert_pdf_to_html(pdf_path)

            if html_content:
                data_availability_section = self.extract_data_availability_from_html(html_content)
                if data_availability_section:
                    source_type = "HTML"
                    logger.info("从HTML成功提取Data Availability部分")
        
        # 2. 如果HTML方法失败，尝试文本转换
        if not data_availability_section:
            logger.info("方法2: HTML转换失败，尝试文本转换...")
            text_content = self.convert_pdf_to_text(pdf_path)
            
            if text_content:
                data_availability_section = self.extract_data_availability_from_text(text_content)
                if data_availability_section:
                    source_type = "文本"
                    logger.info("从文本成功提取Data Availability部分")
            else:
                logger.warning("文本转换失败")
        
        if not data_availability_section:
            logger.warning("无法提取Data Availability部分")
            
            # 如果文本转换成功但没有找到Data Availability部分，尝试在整个文本中搜索ID
            text_content = self.convert_pdf_to_text(pdf_path)
            if text_content:
                logger.info("将在整个文本中搜索结构ID...")
                data_availability_section = text_content
                source_type = "整个文本"
            else:
                return {
                    "pdb_ids": [],
                    "emdb_ids": [],
                    "pdb_contexts": [],
                    "emdb_contexts": [],
                    "data_availability_section_found": False,
                    "extraction_method": "failed",
                    "source_type": "none"
                }
        
        # 3. 在Data Availability部分中提取PDB和EMDB IDs
        logger.info("在Data Availability部分中搜索结构ID...")
        
        pdb_ids, pdb_contexts = self.extract_pdb_ids(data_availability_section)
        emdb_ids, emdb_contexts = self.extract_emdb_ids(data_availability_section)
        
        logger.info(f"提取到的PDB IDs: {pdb_ids}")
        logger.info(f"提取到的EMDB IDs: {emdb_ids}")
        
        # 过滤PDB IDs，保留较新的结构（初步过滤）
        pdb_ids, pdb_contexts = self.filter_pdb_ids_by_first_digit(pdb_ids, pdb_contexts, emdb_ids, emdb_contexts)
        
        # 构建结果
        result = {
            "pdb_ids": pdb_ids,
            "emdb_ids": emdb_ids,
            "pdb_contexts": pdb_contexts,
            "emdb_contexts": emdb_contexts,
            "data_availability_section_found": source_type in ["HTML", "文本"],
            "extraction_method": source_type,
            "source_type": source_type,
            "preliminary_filtered": True
        }
        
        # 记录结果
        if pdb_ids:
            logger.info(f"初步过滤后保留的PDB IDs ({len(pdb_ids)}个): {pdb_ids}")
        else:
            logger.info("未找到PDB ID")
        
        if emdb_ids:
            logger.info(f"找到的EMDB IDs ({len(emdb_ids)}个): {emdb_ids}")
        
        return result
    
    def extract_structure_ids(self, text: str) -> Dict[str, Any]:
        """从文本中提取所有结构ID - 保持与现有接口兼容"""
        if not self.config.EXTRACT_STRUCTURE_IDS:
            return {"pdb_ids": [], "emdb_ids": [], "extraction_method": "disabled"}
        
        start_time = time.time()
        
        # 直接使用文本提取（备用方法）
        pdb_ids, pdb_contexts = self.extract_pdb_ids(text)
        emdb_ids, emdb_contexts = self.extract_emdb_ids(text)
        
        # 过滤PDB IDs（初步过滤）
        pdb_ids, pdb_contexts = self.filter_pdb_ids_by_first_digit(pdb_ids, pdb_contexts, emdb_ids, emdb_contexts)
        
        result = {
            "pdb_ids": pdb_ids,
            "emdb_ids": emdb_ids,
            "pdb_contexts": pdb_contexts,
            "emdb_contexts": emdb_contexts,
            "extraction_method": "full_text",
            "data_availability_section_found": False,
            "preliminary_filtered": True
        }
        
        elapsed = time.time() - start_time
        logger.info(f"全文提取结构ID完成 ({elapsed:.2f}秒): PDB={len(pdb_ids)}, EMDB={len(emdb_ids)}")
        
        return result

# ---------- PDF解析核心 ----------
class PDFParser:
    """PDF解析器"""
    
    def __init__(self, config: LiteratureParserConfig = None):
        self.config = config or LiteratureParserConfig()
        self.extracted_data_cache = {}
        self.structure_extractor = StructureIDExtractor(config)
        
        # 改进的章节识别关键词（参考extract_sections.py）
        self.section_patterns = {
            'abstract': [
                r'^abstract\b',
                r'^summary\b',
                r'^\s*abstract\b',
                r'^\s*摘要\b',
                r'^\s*概要\b',
            ],
            'introduction': [
                r'^introduction\b',
                r'^1[\.\s]+introduction\b',
                r'^\s*introduction\b',
                r'^background\b',
                r'^\s*引言\b',
                r'^\s*背景\b',
                r'^1[\.\s]+引言\b',
                r'^1[\.\s]+背景\b',
            ],
            'methods': [
                r'^methods\b',
                r'^4[\.\s]+methods\b',
                r'^\s*methods\b',
                r'^materials and methods\b',
                r'^experimental methods\b',
                r'^materials\s+and\s+methods\b',
                r'^methodology\b',
                r'^experimental procedures\b',
                r'^experimental section\b',
                r'^\s*方法\b',
                r'^\s*实验方法\b',
                r'^\s*材料与方法\b',
                r'^4[\.\s]+方法\b',
            ],
            'results': [
                r'^results\b',
                r'^2[\.\s]+results\b',
                r'^\s*results\b',
                r'^experimental results\b',
                r'^main results\b',
                r'^findings\b',
                r'^\s*结果\b',
                r'^\s*发现\b',
                r'^2[\.\s]+结果\b',
            ],
            'discussion': [
                r'^discussion\b',
                r'^3[\.\s]+discussion\b',
                r'^\s*discussion\b',
                r'^conclusions\b',
                r'^conclusion\b',
                r'^\s*讨论\b',
                r'^\s*结论\b',
                r'^\s*讨论与分析\b',
                r'^3[\.\s]+讨论\b',
            ],
            'conclusions': [
                r'^conclusions\b',
                r'^concluding remarks\b',
                r'^\s*conclusions\b',
                r'^\s*总结\b',
                r'^\s*结论\b',
            ],
            'data_availability': [
                r'^data availability\b',
                r'^data and materials availability\b',
                r'^data and code availability\b',
                r'^data availability statement\b',
                r'^availability statement\b',
                r'^\s*数据可用性\b',
                r'^\s*数据与材料可用性\b',
            ],
            'references': [
                r'^references\b',
                r'^bibliography\b',
                r'^literature cited\b',
                r'^works cited\b',
                r'^\s*参考文献\b',
                r'^\s*文献引用\b',
            ],
            'acknowledgments': [
                r'^acknowledgments\b',
                r'^acknowledgements\b',
                r'^acknowledgment\b',
                r'^acknowledgement\b',
                r'^\s*致谢\b',
            ],
            'author_contributions': [
                r'^author contributions\b',
                r'^contributions\b',
                r'^author information\b',
                r'^\s*作者贡献\b',
            ],
            'conflicts': [
                r'^conflict of interest\b',
                r'^competing interests\b',
                r'^disclosure\b',
                r'^\s*利益冲突\b',
            ],
            'figure_legends': [
                r'^figure legends\b',
                r'^figure captions\b',
                r'^legends\b',
                r'^\s*图例\b',
            ]
        }
    
    def clear_cache(self):
        """清除解析缓存"""
        self.extracted_data_cache.clear()
        logger.info("PDF解析缓存已清除")
    
    def parse_pdf(self, pdf_path: Union[str, Path], force_reparse: bool = False) -> Dict[str, Any]:
        """解析PDF文件"""
        start_time = time.time()
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF文件不存在: {pdf_path}")
        
        logger.info(f"开始解析PDF: {pdf_path.name}")
        
        # 检查缓存（除非强制重新解析）
        file_hash = self._calculate_file_hash(pdf_path)
        if not force_reparse and file_hash in self.extracted_data_cache:
            logger.info(f"使用缓存数据: {pdf_path.name}")
            return self.extracted_data_cache[file_hash]
        
        result = {
            "metadata": {},
            "text": "",
            "sections": {},
            "figures": [],
            "tables": [],
            "references": [],
            "statistics": {},
            "structure_ids": {}  # 新增：结构ID提取结果
        }
        
        try:
            # 使用PyMuPDF提取基础信息
            with pymupdf.open(str(pdf_path)) as doc:
                result["metadata"] = self._extract_pdf_metadata(doc)
                full_text = self._extract_full_text(doc)
                result["text"] = full_text
                
                # 尝试提取HTML内容用于更好的章节识别
                html_content = None
                if self.config.USE_HTML_FOR_SECTION_PARSING:
                    try:
                        html_content = self.structure_extractor.convert_pdf_to_html(pdf_path)
                    except Exception as e:
                        logger.debug(f"获取HTML内容失败: {e}")
                
                # 使用改进的章节识别（参考extract_sections.py方法）
                sections = self._identify_sections_advanced(full_text, html_content)
                result["sections"] = sections

                # 检查是否已从HTML转换中获取了data_availability_section，避免重复转换
                data_availability_section = sections.get("data_availability", "") if sections else ""

                # 新增：使用严格按照extract_structure_ids.py标准的结构ID提取器
                # 如果data_availability已从章节识别中提取，传递给提取器以避免重复解析
                if self.config.EXTRACT_STRUCTURE_IDS:
                    # 复用已有的HTML内容和章节数据，避免重复转换PDF
                    structure_result = self.structure_extractor.process_pdf_extract_ids(
                        pdf_path,
                        pre_extracted_html=html_content,
                        pre_extracted_sections=sections
                    )
                        
                    if "pdb_ids" in structure_result:
                        pdb_ids = structure_result["pdb_ids"]
                        original_pdb_ids = structure_result.get("original_pdb_ids", [])
                        if original_pdb_ids:
                            logger.info(f"初步过滤: {len(original_pdb_ids)} → {len(pdb_ids)} 个PDB IDs")
                        else:
                            logger.info(f"提取到 {len(pdb_ids)} 个PDB IDs")
                    
                    if "emdb_ids" in structure_result:
                        emdb_ids = structure_result["emdb_ids"]
                        logger.info(f"提取到 {len(emdb_ids)} 个EMDB IDs")
                    
                    # 标记过滤状态
                    structure_result["filtering_status"] = {
                        "preliminary_filter_applied": structure_result.get("preliminary_filtered", False),
                        "emdb_association_filter_applied": False,  # 将由 structure_manager.py 处理
                        "needs_further_processing": True  # 需要进一步处理
                    }
                    
                    result["structure_ids"] = structure_result

                # 新增：通过DOI获取额外的PDB/EMDB ID（如果存在DOI）
                if self.config.EXTRACT_STRUCTURE_IDS and HAS_RCSB_SEARCH:
                    doi = self._extract_doi_from_metadata(result.get("metadata", {}), result.get("text", ""))
                    if doi:
                        logger.info(f"检测到DOI: {doi}，尝试通过RCSB Search API获取关联结构ID...")
                        try:
                            structure_result = result.get("structure_ids", {})
                            enhanced_result = self._enhance_structure_ids_with_doi(
                                structure_result, doi
                            )
                            if enhanced_result:
                                result["structure_ids"] = enhanced_result
                                logger.info(f"DOI增强后的结构ID: PDB={enhanced_result.get('pdb_ids', [])}, EMDB={enhanced_result.get('emdb_ids', [])}")
                        except Exception as doi_error:
                            logger.warning(f"DOI结构ID获取失败，回退到PDF提取结果: {doi_error}")

                result["figures"] = self._extract_figures(doc)
                result["statistics"] = self._calculate_statistics(doc, result)
        
        except Exception as e:
            logger.error(f"PyMuPDF解析失败: {e}")
            # 回退到pdfplumber
            if HAS_PDFPLUMBER:
                try:
                    pdf_data = self._parse_with_pdfplumber(pdf_path)
                    result.update(pdf_data)
                    
                    # 对于pdfplumber，尝试获取HTML内容
                    html_content = None
                    if self.config.USE_HTML_FOR_SECTION_PARSING:
                        try:
                            html_content = self.structure_extractor.convert_pdf_to_html(pdf_path)
                        except Exception as e:
                            logger.debug(f"获取HTML内容失败: {e}")
                    
                    # 使用改进的章节识别
                    if "text" in result:
                        sections = self._identify_sections_advanced(result.get("text", ""), html_content)
                        result["sections"] = sections

                    # 如果回退成功且有文本，尝试提取结构ID
                    if self.config.EXTRACT_STRUCTURE_IDS:
                        # 复用已有的HTML内容和章节数据
                        structure_result = self.structure_extractor.process_pdf_extract_ids(
                            pdf_path,
                            pre_extracted_html=html_content,
                            pre_extracted_sections=sections
                        )
                        
                        structure_result["filtering_status"] = {
                            "preliminary_filter_applied": structure_result.get("preliminary_filtered", False),
                            "emdb_association_filter_applied": False,  # 将由 structure_manager.py 处理
                            "needs_further_processing": True  # 需要进一步处理
                        }
                        
                        result["structure_ids"] = structure_result
                except Exception as pdfplumber_error:
                    logger.error(f"pdfplumber解析也失败: {pdfplumber_error}")
            else:
                logger.error("pdfplumber未安装，无法回退到pdfplumber解析")
        
        # 确保数据结构完整
        if "sections" not in result:
            result["sections"] = {}
        
        # 缓存结果
        self.extracted_data_cache[file_hash] = result
        
        elapsed = time.time() - start_time
        logger.info(f"✅ PDF解析完成 ({elapsed:.2f}秒): {pdf_path.name} ({len(result['text'])} 字符)")
        
        # 输出章节提取结果
        if result.get("sections"):
            extracted_sections = [k for k, v in result["sections"].items() if v and len(v.strip()) > self.config.MIN_SECTION_LENGTH]
            if extracted_sections:
                logger.info(f"📚 提取章节: {', '.join(extracted_sections)}")
            else:
                logger.warning("⚠️ 没有提取到有效的章节内容")
        
        # 输出结构ID提取结果
        if result.get("structure_ids"):
            structure_info = result["structure_ids"]
            if structure_info.get("pdb_ids") or structure_info.get("emdb_ids"):
                pdb_count = len(structure_info.get("pdb_ids", []))
                emdb_count = len(structure_info.get("emdb_ids", []))
                logger.info(f"提取到结构ID: PDB={pdb_count}, EMDB={emdb_count}")
                logger.info(f"   提取方法: {structure_info.get('extraction_method', 'unknown')}")

                # 显示DOI增强信息
                if structure_info.get("doi_enhanced"):
                    doi = structure_info.get("doi", "")
                    doi_source = structure_info.get("source_details", {}).get("doi_lookup", {})
                    doi_pdb_count = len(doi_source.get("doi_pdb_ids", []))
                    doi_emdb_count = len(doi_source.get("doi_emdb_ids", []))
                    logger.info(f"   DOI增强: {doi}")
                    logger.info(f"     - RCSB API获取: {doi_pdb_count} 个PDB, {doi_emdb_count} 个EMDB")

                if structure_info.get("filter_applied"):
                    logger.info(f"   应用层过滤: 已应用")
                    if structure_info.get("filter_info", {}).get("total_pdb_ids"):
                        total = structure_info["filter_info"]["total_pdb_ids"]
                        kept = structure_info["filter_info"].get("filtered_pdb_count", total)
                        logger.info(f"   过滤结果: {total} -> {kept}")

        # 新增：获取结构元信息并保存到离线数据库
        if HAS_STRUCTURE_MANAGER and result.get("structure_ids"):
            structure_ids = result["structure_ids"]
            pdb_ids = structure_ids.get("pdb_ids", [])
            emdb_ids = structure_ids.get("emdb_ids", [])

            if pdb_ids or emdb_ids:
                logger.info(f"开始获取结构元信息: PDB={len(pdb_ids)}, EMDB={len(emdb_ids)}")
                try:
                    # 创建结构元信息获取器
                    fetcher = StructureMetadataFetcher()

                    # 准备source_info用于文献关联过滤
                    source_info = structure_ids.get("source_details", {}).get("doi_lookup", {})
                    if not source_info and structure_ids.get("doi"):
                        source_info = {
                            "doi": structure_ids.get("doi"),
                            "doi_pdb_ids": [],
                            "doi_emdb_ids": [],
                            "source": "pdf_extraction"
                        }

                    # 构建传递给process_structure_ids的参数
                    structure_ids_dict = {
                        "pdb_ids": pdb_ids,
                        "emdb_ids": emdb_ids,
                        "source_info": source_info
                    }

                    # 调用structure_manager获取元信息并保存到离线数据库
                    metadata_result = fetcher.process_structure_ids(
                        structure_ids_dict,
                        force_update=True,
                        fetch_uniprot=True,
                        cleanup_old_data=True
                    )

                    # 将元信息添加到结果中
                    if metadata_result:
                        result["structure_metadata"] = {
                            "pdb_metadata": metadata_result.get("pdb_metadata", {}),
                            "emdb_metadata": metadata_result.get("emdb_metadata", {}),
                            "uniprot_data": metadata_result.get("uniprot_data", {}),
                            "filter_info": metadata_result.get("filter_info", {}),
                            "status": metadata_result.get("status", "completed")
                        }
                        logger.info(f"结构元信息获取完成: PDB={len(metadata_result.get('pdb_metadata', {}))}, EMDB={len(metadata_result.get('emdb_metadata', {}))}")
                    else:
                        logger.warning("结构元信息获取返回为空")

                except Exception as e:
                    logger.error(f"获取结构元信息失败: {e}")

        return result
    
    def _calculate_file_hash(self, file_path: Path) -> str:
        """计算文件哈希"""
        with open(file_path, 'rb') as f:
            return hashlib.md5(f.read()).hexdigest()
    
    def _extract_pdf_metadata(self, doc) -> Dict[str, Any]:
        """提取PDF元数据"""
        metadata = {}
        
        try:
            # 标准PDF元数据
            pdf_metadata = doc.metadata
            if pdf_metadata:
                metadata.update({
                    "title": pdf_metadata.get("title", "").strip(),
                    "author": pdf_metadata.get("author", "").strip(),
                    "subject": pdf_metadata.get("subject", "").strip(),
                    "keywords": pdf_metadata.get("keywords", "").strip(),
                    "creator": pdf_metadata.get("creator", "").strip(),
                    "producer": pdf_metadata.get("producer", "").strip(),
                    "creation_date": pdf_metadata.get("creationDate", ""),
                    "modification_date": pdf_metadata.get("modDate", ""),
                })
            
            # 文档信息
            metadata.update({
                "page_count": len(doc),
                "file_size": os.path.getsize(doc.name),
                "is_scanned": self._detect_if_scanned(doc)
            })
            
        except Exception as e:
            logger.error(f"提取PDF元数据失败: {e}")
        
        return metadata
    
    def _extract_full_text(self, doc) -> str:
        """提取全文文本"""
        full_text = []
        
        for page_num in range(min(len(doc), self.config.PDF_MAX_PAGES)):
            try:
                page = doc.load_page(page_num)
                text = page.get_text()
                if text.strip():
                    full_text.append(f"--- Page {page_num + 1} ---\n{text}")
            except Exception as e:
                logger.warning(f"提取第 {page_num + 1} 页文本失败: {e}")
        
        return "\n\n".join(full_text)
    
    def _identify_sections_advanced(self, text: str, html_content: str = None) -> Dict[str, str]:
        """改进的章节识别：参考extract_sections.py的方法"""
        # 方法1：如果提供了HTML内容，使用HTML解析（更准确）
        if html_content and self.config.USE_HTML_FOR_SECTION_PARSING:
            try:
                html_sections = self._extract_sections_from_html(html_content)
                
                # 检查是否提取到了关键章节
                key_sections = ["abstract", "introduction", "methods", "results", 
                              "discussion", "conclusions", "data_availability"]
                extracted_key_sections = [s for s in key_sections if html_sections.get(s) and len(html_sections[s].strip()) > 50]
                
                if len(extracted_key_sections) >= 2:  # 至少提取到2个关键章节
                    logger.info(f"使用HTML解析的章节信息，提取到 {len(extracted_key_sections)} 个关键章节")
                    return html_sections
                else:
                    logger.info(f"HTML解析只提取到 {len(extracted_key_sections)} 个关键章节，尝试文本解析")
            except Exception as e:
                logger.warning(f"HTML章节提取失败: {e}")
        
        # 方法2：使用改进的文本章节识别（参考extract_sections.py）
        logger.info("使用改进的文本解析进行章节识别")
        return self._extract_sections_by_patterns(text)
    
    def _extract_sections_from_html(self, html_content: str) -> Dict[str, str]:
        """从HTML中提取章节（兼容原方法）"""
        import re
        
        sections = {key: "" for key in self.section_patterns.keys()}
        
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # 移除脚本和样式标签
            for script in soup(["script", "style", "meta", "link"]):
                script.decompose()
            
            # 获取所有文本
            all_text = soup.get_text(separator='\n', strip=True)
            
            # 如果HTML内容较多，使用文本解析
            if len(all_text) > 1000:
                return self._extract_sections_by_patterns(all_text)
            
            # 尝试查找章节标题
            lines = all_text.split('\n')
            current_section = 'header'
            section_content = []
            
            for i, line in enumerate(lines):
                line_stripped = line.strip()
                if not line_stripped:
                    if section_content:
                        section_content.append("")
                    continue
                
                # 检查是否匹配任何章节标题
                section_found = None
                for section_name, patterns in self.section_patterns.items():
                    for pattern in patterns:
                        if re.search(pattern, line_stripped, re.IGNORECASE):
                            # 如果匹配到新章节，保存当前章节
                            if section_content:
                                if current_section in sections:
                                    sections[current_section] += '\n' + '\n'.join(section_content)
                                else:
                                    sections[current_section] = '\n'.join(section_content)
                            
                            # 开始新章节
                            current_section = section_name
                            section_content = [line]  # 包含标题本身
                            section_found = True
                            break
                    if section_found:
                        break
                
                # 如果没匹配到章节标题，添加到当前章节内容
                if not section_found:
                    section_content.append(line)
            
            # 保存最后一个章节
            if section_content:
                if current_section in sections:
                    sections[current_section] += '\n' + '\n'.join(section_content)
                else:
                    sections[current_section] = '\n'.join(section_content)
            
            # 清理每个章节的内容
            for section_name in sections:
                sections[section_name] = sections[section_name].strip()
            
            return sections
            
        except Exception as e:
            logger.error(f"HTML章节提取失败: {e}")
            # 回退到文本解析
            return self._extract_sections_by_patterns(html_content if len(html_content) < 10000 else html_content[:10000])
    
    def _extract_sections_by_patterns(self, text: str) -> Dict[str, str]:
        """
        使用模式匹配提取章节（参考extract_sections.py的核心方法）
        
        Args:
            text: 输入的文本内容
            
        Returns:
            Dict[str, str]: 章节名称到章节内容的映射
        """
        import re
        
        sections = {}
        
        if not text or len(text) < 100:
            return sections
        
        lines = text.split('\n')
        current_section = 'header'  # 默认开始部分
        section_content = []
        
        for i, line in enumerate(lines):
            line_stripped = line.strip()
            
            # 跳过空行
            if not line_stripped:
                if section_content:  # 保持空行作为分隔
                    section_content.append("")
                continue
            
            # 检查是否匹配任何章节标题
            section_found = None
            for section_name, patterns in self.section_patterns.items():
                for pattern in patterns:
                    if re.search(pattern, line_stripped, re.IGNORECASE):
                        # 如果匹配到新章节，保存当前章节
                        if section_content:
                            if current_section in sections:
                                # 合并同名章节
                                sections[current_section] += '\n' + '\n'.join(section_content)
                            else:
                                sections[current_section] = '\n'.join(section_content)
                        
                        # 开始新章节
                        current_section = section_name
                        section_content = [line]  # 包含标题本身
                        section_found = True
                        break
                if section_found:
                    break
            
            # 如果没匹配到章节标题，添加到当前章节内容
            if not section_found:
                section_content.append(line)
        
        # 保存最后一个章节
        if section_content:
            if current_section in sections:
                sections[current_section] += '\n' + '\n'.join(section_content)
            else:
                sections[current_section] = '\n'.join(section_content)
        
        # 如果没能识别出标准章节，尝试其他方法
        if not sections or (len(sections) == 1 and 'header' in sections):
            sections = self._split_by_common_patterns(text)
        
        # 清理每个章节的内容
        for section_name in sections:
            content = sections[section_name].strip()
            # 移除标题行本身（如果内容以标题开始）
            lines = content.split('\n')
            if len(lines) > 1:
                # 检查第一行是否包含章节标题关键词
                first_line = lines[0].strip().lower()
                is_title_line = False
                for patterns in self.section_patterns.values():
                    for pattern in patterns:
                        if re.search(pattern, first_line, re.IGNORECASE):
                            is_title_line = True
                            break
                    if is_title_line:
                        break
                
                if is_title_line:
                    # 移除标题行，保留后续内容
                    sections[section_name] = '\n'.join(lines[1:]).strip()
                else:
                    sections[section_name] = content
            else:
                sections[section_name] = content
        
        # 移除过短的章节（可能是误识别）
        filtered_sections = {}
        for section_name, content in sections.items():
            if len(content.strip()) >= self.config.MIN_SECTION_LENGTH:
                filtered_sections[section_name] = content
        
        return filtered_sections
    
    def _split_by_common_patterns(self, text: str) -> Dict[str, str]:
        """
        通过常见模式分割文本（备用方法）
        
        Args:
            text: 输入的文本内容
            
        Returns:
            Dict[str, str]: 章节名称到章节内容的映射
        """
        import re
        
        sections = {}
        
        if not text:
            return sections
        
        # 按常见标题分割
        patterns = [
            (r'\n\s*(?:ABSTRACT|Abstract|Summary|摘要|概要)\s*\n', 'abstract'),
            (r'\n\s*(?:INTRODUCTION|Introduction|Background|引言|背景)\s*\n', 'introduction'),
            (r'\n\s*(?:RESULTS|Results|Findings|EXPERIMENTAL RESULTS|结果|发现)\s*\n', 'results'),
            (r'\n\s*(?:DISCUSSION|Discussion|CONCLUSIONS|Conclusion|讨论|结论)\s*\n', 'discussion'),
            (r'\n\s*(?:METHODS|Methods|MATERIALS AND METHODS|Materials and Methods|METHODOLOGY|Methodology|方法|实验方法|材料与方法)\s*\n', 'methods'),
            (r'\n\s*(?:DATA AVAILABILITY|Data Availability|数据可用性)\s*\n', 'data_availability'),
            (r'\n\s*(?:REFERENCES|References|BIBLIOGRAPHY|Bibliography|参考文献|文献引用)\s*\n', 'references'),
            (r'\n\s*(?:ACKNOWLEDGMENTS|Acknowledgments|ACKNOWLEDGEMENTS|Acknowledgements|致谢)\s*\n', 'acknowledgments'),
        ]
        
        positions = []
        for pattern, section_name in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                positions.append((match.start(), match.group(), section_name))
        
        # 按位置排序
        positions.sort(key=lambda x: x[0])
        
        if not positions:
            # 如果没找到任何标题，将整个文本作为"full_text"
            sections['full_text'] = text
            return sections
        
        # 分割文本
        start_idx = 0
        for i, (pos, title, section_name) in enumerate(positions):
            # 第一个标题前的内容
            if i == 0:
                if pos > 0:
                    sections['header'] = text[start_idx:pos]
            
            # 确定当前章节的结束位置
            if i < len(positions) - 1:
                end_idx = positions[i+1][0]
            else:
                end_idx = len(text)
            
            sections[section_name] = text[pos:end_idx]
            start_idx = pos
        
        return sections
    
    def _extract_figures(self, doc) -> List[Dict[str, Any]]:
        """提取图表信息"""
        figures = []
        
        if not self.config.PDF_EXTRACT_IMAGES:
            return figures
        
        try:
            for page_num in range(min(len(doc), 50)):  # 限制前50页
                page = doc.load_page(page_num)
                images = page.get_images()
                
                for img_index, img in enumerate(images):
                    try:
                        xref = img[0]
                        base_image = doc.extract_image(xref)
                        
                        figure_info = {
                            "page": page_num + 1,
                            "index": img_index,
                            "width": base_image.get("width", 0),
                            "height": base_image.get("height", 0),
                            "format": base_image.get("ext", "unknown"),
                            "size": len(base_image.get("image", b"")),
                            "caption": self._extract_figure_caption(page, img_index)
                        }
                        
                        figures.append(figure_info)
                        
                    except Exception as e:
                        logger.debug(f"提取图像 {img_index} 失败: {e}")
                        
        except Exception as e:
            logger.error(f"提取图表失败: {e}")
        
        return figures
    
    def _extract_figure_caption(self, page, img_index: int) -> str:
        """尝试提取图表标题"""
        # 简单实现：查找图像附近的文本
        return ""
    
    def _extract_tables(self, pdf_path: Path) -> List[Dict[str, Any]]:
        """提取表格数据"""
        tables = []
        
        if not self.config.PDF_EXTRACT_TABLES:
            return tables
        
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page_num, page in enumerate(pdf.pages[:50]):  # 限制前50页
                    page_tables = page.extract_tables()
                    
                    for table_index, table in enumerate(page_tables):
                        if table:
                            table_data = {
                                "page": page_num + 1,
                                "index": table_index,
                                "rows": len(table),
                                "columns": len(table[0]) if table[0] else 0,
                                "data": table,
                                "caption": self._extract_table_caption(page, table_index)
                            }
                            tables.append(table_data)
                            
        except Exception as e:
            logger.error(f"提取表格失败: {e}")
        
        return tables
    
    def _extract_table_caption(self, page, table_index: int) -> str:
        """尝试提取表格标题"""
        return ""
    
    def _parse_with_pdfplumber(self, pdf_path: Path) -> Dict[str, Any]:
        """使用pdfplumber解析PDF"""
        result = {
            "text": "",
            "tables": []
        }
        
        try:
            with pdfplumber.open(pdf_path) as pdf:
                # 提取文本
                text_parts = []
                for page in pdf.pages[:self.config.PDF_MAX_PAGES]:
                    text = page.extract_text()
                    if text:
                        text_parts.append(text)
                
                result["text"] = "\n\n".join(text_parts)
                
                # 提取表格
                if self.config.PDF_EXTRACT_TABLES:
                    result["tables"] = self._extract_tables(pdf_path)
                
        except Exception as e:
            logger.error(f"pdfplumber解析失败: {e}")

        return result

    def _extract_doi_from_metadata(self, metadata: Dict, text: str = "") -> Optional[str]:
        """
        从PDF元数据或文本中提取DOI

        Args:
            metadata: PDF元数据字典
            text: PDF文本内容

        Returns:
            DOI字符串，如果未找到则返回None
        """
        # 1. 首先尝试从元数据中获取
        doi = None

        # 检查元数据中的DOI字段
        for field in ['doi', 'DOI', 'DOI号']:
            if field in metadata and metadata[field]:
                doi = metadata[field]
                break

        # 2. 如果元数据中没有DOI，从文本中提取
        if not doi and text:
            doi_patterns = [
                r'\b(10\.\d{4,9}/[-._;()/:A-Z0-9]+)\b',  # 标准DOI格式
                r'(?:DOI|doi)[:\s]*((?:10\.\d{4,9}/[-._;()/:A-Z0-9]+))',  # DOI: 10.xxx
                r'https?://doi\.org/((?:10\.\d{4,9}/[-._;()/:A-Z0-9]+))',  # DOI URL
            ]

            for pattern in doi_patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    doi = match.group(1)
                    # 清理DOI
                    doi = doi.strip().rstrip('.').rstrip(')')
                    break

        if doi:
            logger.info(f"提取到DOI: {doi}")
            return doi

        return None

    def _enhance_structure_ids_with_doi(
        self,
        structure_result: Dict[str, Any],
        doi: str
    ) -> Dict[str, Any]:
        """
        通过DOI查询RCSB Search API获取额外的PDB/EMDB ID

        Args:
            structure_result: 当前的结构ID提取结果
            doi: 文献的DOI

        Returns:
            增强后的结构ID结果（包含DOI获取的ID）
        """
        if not HAS_RCSB_SEARCH:
            logger.warning("RCSB Search API不可用，跳过DOI增强")
            return structure_result

        try:
            # 创建RCSB搜索客户端
            search_client = RCSBPDBSearch()

            # 调用DOI搜索方法，同时获取PDB和EMDB ID
            doi_pdb_ids, doi_emdb_ids = search_client.search_by_doi_with_emdb(doi)

            if not doi_pdb_ids and not doi_emdb_ids:
                logger.info(f"DOI {doi} 未找到关联的PDB/EMDB结构")
                return structure_result

            logger.info(f"DOI {doi} 找到: {len(doi_pdb_ids)} 个PDB, {len(doi_emdb_ids)} 个EMDB")

            # 获取现有的结构ID
            existing_pdb_ids = set(structure_result.get("pdb_ids", []))
            existing_emdb_ids = set(structure_result.get("emdb_ids", []))

            # 合并PDB ID（去重）
            merged_pdb_ids = list(existing_pdb_ids.union(set(doi_pdb_ids)))

            # 合并EMDB ID（去重）
            merged_emdb_ids = list(existing_emdb_ids.union(set(doi_emdb_ids)))

            # 创建增强后的结果
            enhanced_result = dict(structure_result)
            enhanced_result["pdb_ids"] = merged_pdb_ids
            enhanced_result["emdb_ids"] = merged_emdb_ids

            # 记录来源信息
            enhanced_result["extraction_method"] = structure_result.get("extraction_method", "pdf_text")
            enhanced_result["doi_enhanced"] = True
            enhanced_result["doi"] = doi

            # 添加DOI获取的ID来源信息
            doi_source_info = {
                "doi": doi,
                "doi_pdb_ids": doi_pdb_ids,
                "doi_emdb_ids": doi_emdb_ids,
                "source": "rcsb_search_api"
            }

            if "source_details" not in enhanced_result:
                enhanced_result["source_details"] = {}

            enhanced_result["source_details"]["doi_lookup"] = doi_source_info

            # 记录新增的ID
            new_pdb_ids = set(doi_pdb_ids) - existing_pdb_ids
            new_emdb_ids = set(doi_emdb_ids) - existing_emdb_ids

            if new_pdb_ids:
                logger.info(f"DOI新增PDB ID: {list(new_pdb_ids)}")
            if new_emdb_ids:
                logger.info(f"DOI新增EMDB ID: {list(new_emdb_ids)}")

            return enhanced_result

        except Exception as e:
            logger.error(f"DOI查询RCSB API失败: {e}")
            return structure_result

    def _detect_if_scanned(self, doc) -> bool:
        """检测是否为扫描PDF"""
        try:
            # 简单检测：如果文本很少但页面很多，可能是扫描件
            total_text = ""
            for i in range(min(5, len(doc))):  # 检查前5页
                page = doc.load_page(i)
                total_text += page.get_text()
            
            return len(total_text.strip()) < 100 and len(doc) > 0
            
        except:
            return False
    
    def _calculate_statistics(self, doc, extracted_data: Dict) -> Dict[str, Any]:
        """计算统计信息"""
        text = extracted_data.get("text", "")
        sections = extracted_data.get("sections", {})
        
        return {
            "total_pages": len(doc),
            "total_characters": len(text),
            "total_words": len(text.split()),
            "section_characters": {k: len(v) for k, v in sections.items() if v},
            "figure_count": len(extracted_data.get("figures", [])),
            "table_count": len(extracted_data.get("tables", [])),
            "reference_count": len(re.findall(r'\[\d+\]', text))  # 简单引用计数
        }

# ---------- AI增强解析（简化版） ----------
class AILiteratureParser:
    """AI增强的文献解析器"""
    
    def __init__(self, config: LiteratureParserConfig = None):
        self.config = config or LiteratureParserConfig()
        self.ai_enabled = self.config.AI_ENABLED
    
    def extract_with_ai(self, pdf_data: Dict[str, Any]) -> Dict[str, Any]:
        """使用AI提取文献信息"""
        start_time = time.time()
        
        if not self.ai_enabled:
            logger.warning("AI功能未启用，跳过AI提取")
            return {}
        
        try:
            text = pdf_data.get("text", "")
            if len(text) < 100:
                logger.warning("文本内容过少，跳过AI提取")
                return {}
            
            # 限制文本长度
            text_for_ai = text[:self.config.AI_MAX_TOKENS * 4]  # 粗略估计
            
            result = {}
            
            # 使用更新后的parse_text_with_llm一次性提取所有信息
            if self.config.AI_EXTRACT_METADATA or self.config.AI_EXTRACT_KEY_FINDINGS:
                ai_result = parse_text_with_llm(text_for_ai)
                
                if ai_result:
                    # 提取元数据
                    if self.config.AI_EXTRACT_METADATA:
                        result["metadata"] = self._extract_metadata_from_ai_result(ai_result)
                    
                    # 提取关键发现
                    if self.config.AI_EXTRACT_KEY_FINDINGS:
                        result["key_findings"] = self._extract_key_findings_from_ai_result(ai_result)
                    
                    # 提取摘要
                    if self.config.AI_GENERATE_SUMMARY:
                        result["summary"] = self._generate_summary_from_ai_result(ai_result, text_for_ai)
            
            elapsed = time.time() - start_time
            logger.info(f"✅ AI提取完成 ({elapsed:.2f}秒): {len(result.get('key_findings', []))} 个关键发现")
            return result
            
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"❌ AI提取失败 ({elapsed:.2f}秒): {e}")
            return {}
    
    def _extract_metadata_from_ai_result(self, ai_result: Dict[str, Any]) -> Dict[str, Any]:
        """从AI结果中提取元数据"""
        metadata = {}
        
        # 映射字段
        field_mapping = {
            "title": "title",
            "authors": "authors",
            "journal": "journal",
            "publication_date": "publication_date",
            "year": "year",
            "doi": "doi",
            "keywords": "keywords",
            "abstract": "abstract",
            "research_method": "research_method",
            "citation_count": "citation_count",
            "impact_factor": "impact_factor"
        }
        
        for field_key, result_key in field_mapping.items():
            if result_key in ai_result and ai_result[result_key] is not None:
                metadata[field_key] = ai_result[result_key]
        
        return metadata
    
    def _extract_key_findings_from_ai_result(self, ai_result: Dict[str, Any]) -> List[Dict[str, Any]]:
        """从AI结果中提取关键发现"""
        key_findings = []
        
        if "key_findings" in ai_result and ai_result["key_findings"]:
            findings = ai_result["key_findings"]
            
            if isinstance(findings, list):
                for i, finding in enumerate(findings):
                    if isinstance(finding, dict):
                        key_findings.append({
                            "id": i + 1,
                            "finding": finding.get("finding", str(finding)),
                            "significance": finding.get("significance", ""),
                            "evidence": finding.get("evidence", ""),
                            "page_reference": finding.get("page_reference", "")
                        })
                    else:
                        key_findings.append({
                            "id": i + 1,
                            "finding": str(finding),
                            "significance": "",
                            "evidence": "",
                            "page_reference": ""
                        })
        
        return key_findings
    
    def _generate_summary_from_ai_result(self, ai_result: Dict[str, Any], text: str) -> Dict[str, str]:
        """从AI结果生成摘要"""
        summary = {
            "overview": "",
            "methods_summary": "",
            "key_results": "",
            "implications": "",
            "limitations": ""
        }
        
        # 从abstract字段生成overview
        if ai_result.get("abstract"):
            summary["overview"] = ai_result["abstract"][:300] + "..." if len(ai_result["abstract"]) > 300 else ai_result["abstract"]
        
        # 从research_method字段生成methods_summary
        if ai_result.get("research_method"):
            summary["methods_summary"] = ai_result["research_method"]
        
        # 从key_findings字段生成key_results
        if ai_result.get("key_findings") and isinstance(ai_result["key_findings"], list):
            key_results = []
            for finding in ai_result["key_findings"][:5]:  # 最多5个
                if isinstance(finding, dict):
                    key_results.append(finding.get("finding", ""))
                else:
                    key_results.append(str(finding))
            summary["key_results"] = "；".join(key_results)
        
        return summary

# ---------- 在线元数据检索 ----------
class OnlineMetadataFetcher:
    """增强的在线元数据检索器 - 整合所有在线来源"""
    
    def __init__(self, config: LiteratureParserConfig = None):
        self.config = config or LiteratureParserConfig()
        self.enabled = self.config.FETCH_METADATA_ONLINE
        self.session = None
        self.default_sources = ["crossref", "pubmed", "doi_org", "scholarly"]
        
    def _ensure_session(self):
        """确保请求会话存在"""
        if self.session is None:
            import requests
            self.session = requests.Session()
            self.session.headers.update({
                'User-Agent': 'LiteratureParser/1.0 (mailto:literature_tool@example.com)',
                'Accept': 'application/json'
            })
    
    def fetch_metadata(self, identifier: str, identifier_type: str = "doi") -> Dict[str, Any]:
        """
        获取元数据的主要入口函数
        
        Args:
            identifier: 标识符（DOI、PMID、标题等）
            identifier_type: 标识符类型，可选值：'doi', 'pmid', 'title', 'arxiv'
        
        Returns:
            元数据字典，包含最佳来源的数据
        """
        if not self.enabled or not identifier:
            return {"success": False, "error": "未启用或标识符为空"}
        
        logger.info(f"🔍 开始获取在线元数据: {identifier_type}={identifier}")
        
        # 根据标识符类型调用不同的获取方法
        if identifier_type == "doi":
            return self.fetch_by_doi(identifier)
        elif identifier_type == "pmid":
            return self.fetch_by_pmid(identifier)
        elif identifier_type == "title":
            return self.fetch_by_title(identifier)
        elif identifier_type == "arxiv":
            return self.fetch_by_arxiv(identifier)
        else:
            return {"success": False, "error": f"不支持的标识符类型: {identifier_type}"}
    
    def fetch_by_doi(self, doi: str) -> Dict[str, Any]:
        """通过DOI获取元数据 - 尝试多个来源并选择最优结果"""
        if not doi:
            return {"success": False, "error": "DOI为空"}
        
        doi = self._clean_doi(doi)
        logger.info(f"🔗 通过DOI获取元数据: {doi}")
        
        metadata_sources = {}
        
        # 1. 首先尝试PubMed（最权威，摘要最完整）
        try:
            pubmed_metadata = self._fetch_from_pubmed_by_doi(doi)
            if pubmed_metadata:
                metadata_sources["pubmed"] = pubmed_metadata
                abstract_len = len(pubmed_metadata.get('abstract', ''))
                logger.info(f"✅ PubMed获取成功, 摘要长度: {abstract_len}")
            else:
                logger.warning(f"⚠️ PubMed返回为空")
        except Exception as e:
            logger.warning(f"PubMed获取失败: {e}")
        
        # 2. 尝试Crossref
        try:
            crossref_metadata = self._fetch_from_crossref(doi)
            if crossref_metadata:
                metadata_sources["crossref"] = crossref_metadata
                logger.info(f"✅ Crossref获取成功")
        except Exception as e:
            logger.debug(f"Crossref获取失败: {e}")
        
        # 3. 尝试DOI.org
        try:
            doi_org_metadata = self._fetch_from_doi_org(doi)
            if doi_org_metadata:
                metadata_sources["doi_org"] = doi_org_metadata
                logger.info(f"✅ DOI.org获取成功")
        except Exception as e:
            logger.debug(f"DOI.org获取失败: {e}")
        
        # 4. 尝试scholarly（Google Scholar）
        try:
            scholarly_metadata = self._fetch_from_scholarly_by_doi(doi)
            if scholarly_metadata:
                metadata_sources["scholarly"] = scholarly_metadata
                logger.info(f"✅ Scholarly获取成功")
        except Exception as e:
            logger.debug(f"Scholarly获取失败: {e}")
        
        # 选择最优结果
        best_metadata = self._select_best_metadata(metadata_sources)
        
        if best_metadata:
            logger.info(f"🏆 选择最佳元数据来源: {best_metadata.get('source', 'unknown')}")
            
            # 确保返回格式统一
            result = {
                "success": True,
                "metadata": best_metadata,
                "sources_tried": list(metadata_sources.keys()),
                "sources_found": [k for k, v in metadata_sources.items() if v],
                "best_source": best_metadata.get('source', 'unknown')
            }
            
            # 记录详细信息
            title = best_metadata.get('title', '')
            if title:
                logger.info(f"📖 获取到的标题: {title[:80]}...")
            
            return result
        else:
            logger.warning(f"❌ 所有在线来源都失败了: {doi}")
            return {
                "success": False,
                "error": "所有在线来源都失败了",
                "sources_tried": list(metadata_sources.keys())
            }
    
    def fetch_by_pmid(self, pmid: str) -> Dict[str, Any]:
        """通过PubMed ID获取元数据"""
        if not pmid or not pmid.isdigit():
            return {"success": False, "error": "无效的PubMed ID"}
        
        logger.info(f"🆔 通过PubMed ID获取元数据: {pmid}")
        
        try:
            self._ensure_session()
            
            # 使用PubMed API获取
            metadata = self._fetch_from_pubmed_by_id(pmid)
            if metadata:
                return {
                    "success": True,
                    "metadata": metadata,
                    "source": "pubmed"
                }
        except Exception as e:
            logger.error(f"PubMed ID获取失败: {e}")
        
        return {"success": False, "error": "无法获取PubMed元数据"}
    
    def fetch_by_title(self, title: str) -> Dict[str, Any]:
        """通过标题搜索元数据"""
        if not title or len(title) < 5:
            return {"success": False, "error": "标题太短"}
        
        logger.info(f"🔍 通过标题搜索元数据: {title[:50]}...")
        
        metadata_sources = {}
        
        try:
            # 1. 尝试scholarly（Google Scholar）
            scholarly_metadata = self._fetch_from_scholarly_by_title(title)
            if scholarly_metadata:
                metadata_sources["scholarly"] = scholarly_metadata
                logger.info(f"✅ Scholarly标题搜索成功")
        except Exception as e:
            logger.debug(f"Scholarly标题搜索失败: {e}")
        
        # 选择最优结果
        best_metadata = self._select_best_metadata(metadata_sources)
        
        if best_metadata:
            return {
                "success": True,
                "metadata": best_metadata,
                "source": best_metadata.get('source', 'unknown')
            }
        else:
            return {"success": False, "error": "标题搜索无结果"}
    
    def fetch_by_arxiv(self, arxiv_id: str) -> Dict[str, Any]:
        """通过arXiv ID获取元数据"""
        if not arxiv_id:
            return {"success": False, "error": "arXiv ID为空"}
        
        logger.info(f"📄 通过arXiv ID获取元数据: {arxiv_id}")
        
        try:
            self._ensure_session()
            
            metadata = self._fetch_from_arxiv(arxiv_id)
            if metadata:
                return {
                    "success": True,
                    "metadata": metadata,
                    "source": "arxiv"
                }
        except Exception as e:
            logger.error(f"arXiv获取失败: {e}")
        
        return {"success": False, "error": "无法获取arXiv元数据"}
    
    def _clean_doi(self, doi: str) -> str:
        """清理DOI字符串"""
        if not doi:
            return ""
        
        doi = doi.strip()
        
        # 如果包含URL，提取DOI部分
        if doi.startswith('http'):
            import re
            match = re.search(r'10\.\d{4,9}/[-._;()/:A-Z0-9]+', doi, re.IGNORECASE)
            if match:
                return match.group(0)
        
        # 移除可能的"doi:"前缀
        if doi.lower().startswith('doi:'):
            doi = doi[4:].strip()
        
        return doi
    
    def _fetch_from_pubmed_by_doi(self, doi: str) -> Optional[Dict[str, Any]]:
        """通过DOI从PubMed获取元数据"""
        try:
            self._ensure_session()
            
            # 1. 通过DOI获取PubMed ID
            search_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
            params = {
                'db': 'pubmed',
                'term': f'{doi}[DOI]',
                'retmode': 'json',
                'email': 'literature_tool@example.com'
            }
            
            response = self.session.get(search_url, params=params, timeout=10)
            if response.status_code != 200:
                return None
            
            data = response.json()
            id_list = data.get('esearchresult', {}).get('idlist', [])
            if not id_list:
                return None
            
            pmid = id_list[0]
            logger.info(f"🔍 PubMed找到ID: {pmid}")
            
            # 2. 通过PubMed ID获取详细信息
            return self._fetch_from_pubmed_by_id(pmid)
            
        except Exception as e:
            logger.debug(f"PubMed DOI查询失败: {e}")
            return None
    
    def _fetch_from_pubmed_by_id(self, pmid: str) -> Optional[Dict[str, Any]]:
        """通过PubMed ID获取详细信息"""
        try:
            fetch_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
            params = {
                'db': 'pubmed',
                'id': pmid,
                'retmode': 'xml',
                'email': 'literature_tool@example.com'
            }

            response = self.session.get(fetch_url, params=params, timeout=15)
            if response.status_code != 200:
                logger.warning(f"PubMed efetch返回状态码: {response.status_code}")
                return None

            import xml.etree.ElementTree as ET
            import re

            # 解析XML
            root = ET.fromstring(response.content)

            # 尝试多种命名空间
            namespaces = [
                {'pubmed': 'http://www.ncbi.nlm.nih.gov'},
                {'pubmed': 'http://www.ncbi.nlm.nih.gov/pubmed'},
                {}  # 无命名空间
            ]

            article = None
            for ns in namespaces:
                if ns:
                    article = root.find('.//pubmed:PubmedArticle', ns)
                else:
                    # 无命名空间模式
                    article = root.find('.//PubmedArticle')
                if article is not None:
                    break

            if article is None:
                # 记录XML内容用于调试
                xml_content = response.content[:500].decode('utf-8', errors='ignore')
                logger.warning(f"无法解析PubMed XML，PMID={pmid}, XML前500字符: {xml_content}")
                return None

            # 提取标题 - 尝试多种方式
            title = ''
            for ns in namespaces:
                if ns:
                    title_elem = article.find('.//pubmed:ArticleTitle', ns)
                else:
                    title_elem = article.find('.//ArticleTitle')
                if title_elem is not None and title_elem.text:
                    title = title_elem.text
                    break

            # 提取作者
            authors = []
            for ns in namespaces:
                author_list = article.findall('.//pubmed:Author', ns) if ns else article.findall('.//Author')
                if author_list:
                    for author_elem in author_list:
                        lastname_elem = author_elem.find('pubmed:LastName', ns) if ns else author_elem.find('LastName')
                        forename_elem = author_elem.find('pubmed:ForeName', ns) if ns else author_elem.find('ForeName')

                        if lastname_elem is not None:
                            author = {
                                'family': lastname_elem.text,
                                'given': forename_elem.text if forename_elem is not None else ''
                            }
                            author['name'] = f"{author['given']} {author['family']}".strip()
                            authors.append(author)
                    break

            # 提取期刊
            journal = ''
            for ns in namespaces:
                journal_elem = article.find('.//pubmed:Title', ns) if ns else article.find('.//Title')
                if journal_elem is not None and journal_elem.text:
                    journal = journal_elem.text
                    break

            # 提取发表日期
            pub_date = ''
            year = None
            for ns in namespaces:
                pub_date_elem = article.find('.//pubmed:PubDate', ns) if ns else article.find('.//PubDate')
                if pub_date_elem is not None:
                    year_elem = pub_date_elem.find('pubmed:Year', ns) if ns else pub_date_elem.find('Year')
                    if year_elem is not None and year_elem.text:
                        year = year_elem.text
                        pub_date = year

                        month_elem = pub_date_elem.find('pubmed:Month', ns) if ns else pub_date_elem.find('Month')
                        if month_elem is not None and month_elem.text:
                            month = month_elem.text
                            pub_date = f"{year}-{self._normalize_month(month)}"
                    break

            # 提取DOI
            doi = ''
            for ns in namespaces:
                article_id_list = article.findall('.//pubmed:ArticleId[@IdType="doi"]', ns) if ns else article.findall('.//ArticleId[@IdType="doi"]')
                if article_id_list:
                    doi = article_id_list[0].text if article_id_list[0].text else ''
                    break

            # 提取摘要
            abstract = ''
            for ns in namespaces:
                abstract_section = article.find('.//pubmed:Abstract', ns) if ns else article.find('.//Abstract')
                if abstract_section is not None:
                    abstract_texts = []
                    for text_elem in abstract_section.findall('pubmed:AbstractText', ns) if ns else abstract_section.findall('AbstractText'):
                        if text_elem.text:
                            label = text_elem.get('Label', '')
                            if not label:
                                abstract_texts.insert(0, text_elem.text)
                            else:
                                abstract_texts.append(text_elem.text)
                    abstract = ' '.join(abstract_texts)
                    break

            # 清理摘要
            if abstract:
                abstract = re.sub(r'\s+', ' ', abstract).strip()

            # 如果没有获取到任何有用信息，记录警告
            if not title and not abstract:
                logger.warning(f"PubMed返回空数据，PMID={pmid}, title='{title}', abstract长度={len(abstract)}")
                return None

            return {
                "title": title,
                "authors": authors,
                "journal": journal,
                "year": int(year) if year and year.isdigit() else None,
                "publication_date": pub_date,
                "doi": doi,
                "abstract": abstract,
                "pmid": pmid,
                "pubmed_url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                "source": "pubmed"
            }

        except Exception as e:
            logger.error(f"PubMed ID查询失败: {e}")
            return None

    def _fetch_from_crossref(self, doi: str) -> Optional[Dict[str, Any]]:
        """从Crossref获取元数据"""
        try:
            self._ensure_session()
            
            url = f"https://api.crossref.org/works/{doi}"
            response = self.session.get(url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                message = data.get('message', {})
                
                # 提取标题
                title = message.get('title', [''])[0] if message.get('title') else ''
                
                # 提取作者
                authors = []
                for author in message.get('author', []):
                    author_dict = {}
                    if author.get('given'):
                        author_dict['given'] = author['given']
                    if author.get('family'):
                        author_dict['family'] = author['family']
                    
                    if author_dict.get('given') or author_dict.get('family'):
                        author_dict['name'] = f"{author_dict.get('given', '')} {author_dict.get('family', '')}".strip()
                        authors.append(author_dict)
                
                # 提取期刊
                journal = message.get('container-title', [''])[0] if message.get('container-title') else ''
                
                # 提取发表日期
                pub_date = ''
                year = None
                
                # 尝试多个日期字段
                date_fields = ['published-print', 'published-online', 'created', 'issued']
                for field in date_fields:
                    date_info = message.get(field, {})
                    date_parts = date_info.get('date-parts', [[]])[0]
                    if date_parts:
                        if len(date_parts) >= 3:
                            year = date_parts[0]
                            pub_date = f"{year}-{date_parts[1]:02d}-{date_parts[2]:02d}"
                            break
                        elif len(date_parts) >= 1:
                            year = date_parts[0]
                            pub_date = str(year)
                            if len(date_parts) >= 2:
                                pub_date = f"{year}-{date_parts[1]:02d}"
                            break
                
                # 提取摘要
                abstract = ''
                if 'abstract' in message:
                    abstract = message['abstract']
                    # 清理HTML标签
                    import re
                    abstract = re.sub(r'<[^>]+>', '', abstract)
                
                # 提取关键词
                keywords = message.get('subject', [])
                
                return {
                    "title": title,
                    "authors": authors,
                    "journal": journal,
                    "year": int(year) if year else None,
                    "publication_date": pub_date,
                    "doi": doi,
                    "abstract": abstract,
                    "keywords": keywords,
                    "citation_count": message.get('is-referenced-by-count', 0),
                    "source": "crossref",
                    "crossref_data": message
                }
        
        except Exception as e:
            logger.debug(f"Crossref获取失败: {e}")

        return None

    def _fetch_from_doi_org(self, doi: str) -> Optional[Dict[str, Any]]:
        """从DOI.org获取元数据"""
        try:
            self._ensure_session()
            
            url = f"https://doi.org/{doi}"
            headers = {
                "Accept": "application/vnd.citationstyles.csl+json",
                "User-Agent": "LiteratureParser/1.0"
            }
            
            response = self.session.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                # 提取作者
                authors = []
                for author in data.get('author', []):
                    author_dict = {}
                    if author.get('given'):
                        author_dict['given'] = author['given']
                    if author.get('family'):
                        author_dict['family'] = author['family']
                    
                    if author_dict.get('given') or author_dict.get('family'):
                        author_dict['name'] = f"{author_dict.get('given', '')} {author_dict.get('family', '')}".strip()
                        authors.append(author_dict)
                
                # 提取日期
                pub_date = ''
                year = None
                if data.get('issued'):
                    date_parts = data['issued'].get('date-parts', [[]])[0]
                    if date_parts:
                        if len(date_parts) >= 3:
                            year = date_parts[0]
                            pub_date = f"{year}-{date_parts[1]:02d}-{date_parts[2]:02d}"
                        elif len(date_parts) >= 1:
                            year = date_parts[0]
                            pub_date = str(year)
                
                return {
                    "title": data.get('title', ''),
                    "authors": authors,
                    "journal": data.get('container-title', ''),
                    "year": int(year) if year else None,
                    "publication_date": pub_date,
                    "doi": doi,
                    "abstract": data.get('abstract', ''),
                    "source": "doi_org",
                    "url": data.get('URL', f"https://doi.org/{doi}")
                }
        
        except Exception as e:
            logger.debug(f"DOI.org获取失败: {e}")
        
        return None
    
    def _fetch_from_scholarly_by_doi(self, doi: str) -> Optional[Dict[str, Any]]:
        """通过DOI从scholarly获取元数据"""
        try:
            # 需要安装scholarly库
            import scholarly
            
            search_query = scholarly.search_pubs(doi)
            result = next(search_query, None)
            
            if result:
                return {
                    "title": result.get('bib', {}).get('title', ''),
                    "authors": result.get('bib', {}).get('author', []),
                    "year": result.get('bib', {}).get('year'),
                    "journal": result.get('bib', {}).get('journal', ''),
                    "citation_count": result.get('num_citations', 0),
                    "url": result.get('pub_url', ''),
                    "source": "scholarly"
                }
        
        except Exception as e:
            logger.debug(f"Scholarly DOI搜索失败: {e}")
        
        return None
    
    def _fetch_from_scholarly_by_title(self, title: str) -> Optional[Dict[str, Any]]:
        """通过标题从scholarly获取元数据"""
        try:
            import scholarly
            
            search_query = scholarly.search_pubs(title)
            result = next(search_query, None)
            
            if result:
                return {
                    "title": result.get('bib', {}).get('title', title),
                    "authors": result.get('bib', {}).get('author', []),
                    "year": result.get('bib', {}).get('year'),
                    "journal": result.get('bib', {}).get('journal', ''),
                    "citation_count": result.get('num_citations', 0),
                    "url": result.get('pub_url', ''),
                    "source": "scholarly"
                }
        
        except Exception as e:
            logger.debug(f"Scholarly标题搜索失败: {e}")
        
        return None
    
    def _fetch_from_arxiv(self, arxiv_id: str) -> Optional[Dict[str, Any]]:
        """从arXiv获取元数据"""
        try:
            self._ensure_session()
            
            # 清理arXiv ID
            arxiv_id = arxiv_id.replace('arxiv:', '').replace('arXiv:', '').strip()
            
            url = f"http://export.arxiv.org/api/query?id_list={arxiv_id}"
            response = self.session.get(url, timeout=10)
            
            if response.status_code == 200:
                import xml.etree.ElementTree as ET
                
                root = ET.fromstring(response.content)
                namespace = '{http://www.w3.org/2005/Atom}'
                
                entry = root.find(f'{namespace}entry')
                if entry is None:
                    return None
                
                # 提取信息
                title_elem = entry.find(f'{namespace}title')
                title = title_elem.text.strip() if title_elem is not None else ''
                
                # 清理arXiv标题中的换行符
                title = title.replace('\n', ' ')
                
                # 提取作者
                authors = []
                author_elems = entry.findall(f'{namespace}author')
                for author_elem in author_elems:
                    name_elem = author_elem.find(f'{namespace}name')
                    if name_elem is not None:
                        authors.append({
                            "name": name_elem.text.strip(),
                            "affiliation": ""
                        })
                
                # 提取摘要
                summary_elem = entry.find(f'{namespace}summary')
                abstract = summary_elem.text.strip() if summary_elem is not None else ''
                abstract = abstract.replace('\n', ' ')
                
                # 提取日期
                published_elem = entry.find(f'{namespace}published')
                published_date = published_elem.text.strip() if published_elem is not None else ''
                year = published_date[:4] if published_date else None
                
                return {
                    "title": title,
                    "authors": authors,
                    "abstract": abstract,
                    "year": int(year) if year and year.isdigit() else None,
                    "publication_date": published_date,
                    "arxiv_id": arxiv_id,
                    "source": "arxiv"
                }
        
        except Exception as e:
            logger.debug(f"arXiv获取失败: {e}")
        
        return None
    
    def _normalize_month(self, month_str: str) -> str:
        """规范化月份字符串"""
        month_dict = {
            'jan': '01', 'feb': '02', 'mar': '03', 'apr': '04',
            'may': '05', 'jun': '06', 'jul': '07', 'aug': '08',
            'sep': '09', 'oct': '10', 'nov': '11', 'dec': '12',
            'january': '01', 'february': '02', 'march': '03', 'april': '04',
            'may': '05', 'june': '06', 'july': '07', 'august': '08',
            'september': '09', 'october': '10', 'november': '11', 'december': '12'
        }
        
        month_lower = month_str.lower().strip()
        
        # 如果是数字，确保是两位数
        if month_lower.isdigit():
            return f"{int(month_lower):02d}"
        
        # 如果是缩写或全称
        if month_lower in month_dict:
            return month_dict[month_lower]
        
        return month_str
    
    def _select_best_metadata(self, metadata_sources: Dict[str, Dict]) -> Optional[Dict[str, Any]]:
        """从多个来源中选择最优的元数据"""
        if not metadata_sources:
            return None

        # 优先使用 PubMed（摘要最完整）
        if "pubmed" in metadata_sources and metadata_sources["pubmed"]:
            pubmed_abstract = metadata_sources["pubmed"].get('abstract', '')
            if pubmed_abstract and len(pubmed_abstract.strip()) > 50:
                logger.info(f"🏆 选择PubMed作为最佳来源（摘要长度: {len(pubmed_abstract)}）")
                return metadata_sources["pubmed"]

        # 如果 PubMed 没有有效摘要，使用评分系统
        best_metadata = None
        best_score = 0

        for source, metadata in metadata_sources.items():
            if not metadata:
                continue

            score = 0

            # 1. 标题质量 (最高优先级)
            title = metadata.get('title', '')
            if title and isinstance(title, str):
                title_clean = title.strip()
                if len(title_clean) > 10:
                    score += 5
                elif len(title_clean) > 0:
                    score += 2

            # 2. 作者信息
            authors = metadata.get('authors', [])
            if authors and isinstance(authors, list) and len(authors) > 0:
                score += 3

            # 3. 期刊信息
            journal = metadata.get('journal', '')
            if journal and isinstance(journal, str) and journal.strip():
                score += 2

            # 4. 发表日期 (非常重要)
            pub_date = metadata.get('publication_date')
            if pub_date:
                score += 4

            # 5. 年份
            year = metadata.get('year')
            if year:
                score += 3

            # 6. 摘要质量（长度）
            abstract = metadata.get('abstract', '')
            if abstract and isinstance(abstract, str):
                abstract_len = len(abstract.strip())
                if abstract_len > 500:
                    score += 10  # 长摘要优先
                elif abstract_len > 200:
                    score += 6
                elif abstract_len > 50:
                    score += 3

            # 7. 来源权威性和摘要完整性
            if source == "pubmed":
                score += 5  # PubMed最权威，且通常有完整摘要
            elif source == "crossref":
                score += 2  # Crossref次之
            
            logger.debug(f"📊 来源 {source} 评分: {score}")
            
            if score > best_score:
                best_score = score
                best_metadata = metadata
        
        return best_metadata
    
    def __del__(self):
        """清理资源"""
        if self.session:
            self.session.close()
            
# ---------- 文献解析管理器 ----------
class LiteratureParserManager:
    """文献解析管理器"""
    
    def __init__(self, config: LiteratureParserConfig = None):
        self.config = config or LiteratureParserConfig()
        self.pdf_parser = PDFParser(config)
        self.ai_parser = AILiteratureParser(config)
        self.metadata_fetcher = OnlineMetadataFetcher(config)
        
    def clear_cache(self):
        """清除所有缓存"""
        self.pdf_parser.clear_cache()
        logger.info("文献解析管理器缓存已清除")
    
    def parse_literature_file(self, file_path: Union[str, Path], force_reparse: bool = False) -> Dict[str, Any]:
        """解析文献文件"""
        start_time = time.time()
        file_path = Path(file_path)
        logger.info(f"开始解析文献文件: {file_path.name}")
        
        result = {
            "success": False,
            "file_info": {},
            "parsed_data": {},
            "errors": []
        }
        
        try:
            # 1. 文件基本信息
            file_info = {
                "filename": file_path.name,
                "file_path": str(file_path),
                "file_size": file_path.stat().st_size,
                "file_hash": self._calculate_file_hash(file_path),
                "extension": file_path.suffix.lower(),
                "last_modified": datetime.fromtimestamp(file_path.stat().st_mtime).isoformat()
            }
            result["file_info"] = file_info
            
            # 2. 根据文件类型解析
            if file_path.suffix.lower() == '.pdf':
                parsed_data = self._parse_pdf_file(file_path, force_reparse)
            elif file_path.suffix.lower() in ['.docx', '.doc']:
                parsed_data = self._parse_docx_file(file_path)
            elif file_path.suffix.lower() in ['.txt', '.md']:
                parsed_data = self._parse_text_file(file_path)
            elif file_path.suffix.lower() == '.bib':
                parsed_data = self._parse_bibtex_file(file_path)
            else:
                raise ValueError(f"不支持的文件格式: {file_path.suffix}")
            
            result["parsed_data"] = parsed_data
            result["success"] = True
            
            # 3. 尝试在线获取补充元数据（先尝试从解析数据中获取DOI）
            doi = None
            if "combined_metadata" in parsed_data:
                doi = parsed_data["combined_metadata"].get("doi")
            
            # 如果没有DOI，尝试从AI数据中获取
            if not doi and "ai_data" in parsed_data and "metadata" in parsed_data["ai_data"]:
                doi = parsed_data["ai_data"]["metadata"].get("doi")
            
            # 如果没有DOI，尝试从PDF元数据中提取
            if not doi and "pdf_data" in parsed_data and "metadata" in parsed_data["pdf_data"]:
                # 尝试从PDF文本中提取DOI
                text = parsed_data.get("pdf_data", {}).get("text", "")
                doi_match = re.search(r'\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b', text, re.IGNORECASE)
                if doi_match:
                    doi = doi_match.group(0)
                    logger.info(f"从PDF文本中提取到DOI: {doi}")
            
            if doi and self.config.FETCH_METADATA_ONLINE:
                logger.info(f"尝试通过DOI获取在线元数据: {doi}")
                online_metadata = self.metadata_fetcher.fetch_by_doi(doi)
                
                if online_metadata:
                    logger.info(f"✅ 在线元数据获取成功: {doi}")
                    # 保存完整的在线元数据
                    parsed_data["online_metadata_raw"] = online_metadata

                    # 提取实际的metadata内容（fetch_by_doi返回{"success":True, "metadata": {...}, ...}）
                    actual_metadata = online_metadata.get("metadata", online_metadata)

                    # 合并在线元数据到combined_metadata（最高优先级）
                    if "combined_metadata" not in parsed_data:
                        parsed_data["combined_metadata"] = {}

                    # 使用在线元数据更新所有字段（在线数据优先级最高）
                    self._merge_metadata_with_priority(
                        parsed_data["combined_metadata"],
                        actual_metadata,
                        "online"
                    )

                    # 特别更新章节数据中的摘要
                    if actual_metadata.get("abstract") and "section_data" in parsed_data:
                        online_abstract = actual_metadata["abstract"]
                        if online_abstract and len(online_abstract) > 50:
                            parsed_data["section_data"]["abstract"] = online_abstract
                            logger.info(f"✅ 用在线摘要更新章节数据 ({len(online_abstract)} 字符)")

                    logger.info("✅ 在线元数据已合并到解析结果")
                else:
                    logger.warning(f"⚠️ 无法通过DOI获取在线元数据: {doi}")
            
            # 如果没有在线元数据，尝试通过标题搜索
            elif self.config.FETCH_METADATA_ONLINE and "combined_metadata" in parsed_data:
                title = parsed_data["combined_metadata"].get("title")
                if title and len(title) > 10:
                    logger.info(f"尝试通过标题搜索在线元数据: {title[:50]}...")
                    online_metadata = self.metadata_fetcher.fetch_by_title(title)
                    
                    if online_metadata:
                        logger.info(f"✅ 通过标题获取在线元数据成功")
                        parsed_data["online_metadata_raw"] = online_metadata

                        # 提取实际的metadata内容
                        actual_metadata = online_metadata.get("metadata", online_metadata)

                        # 合并在线元数据
                        if "combined_metadata" not in parsed_data:
                            parsed_data["combined_metadata"] = {}

                        self._merge_metadata_with_priority(
                            parsed_data["combined_metadata"],
                            actual_metadata,
                            "online"
                        )

                        logger.info("✅ 在线元数据（通过标题）已合并到解析结果")

            # ========== 新增: 优先使用在线摘要，但保留AI解析的长摘要 ==========
            if parsed_data.get("online_metadata_raw"):
                online_meta = parsed_data["online_metadata_raw"]
                # 从metadata中获取abstract（因为merge后可能在metadata中）
                online_abstract = None
                if isinstance(online_meta, dict):
                    online_abstract = online_meta.get("abstract") or online_meta.get("metadata", {}).get("abstract")

                # 获取AI解析的摘要
                ai_abstract = None
                if parsed_data.get("ai_data") and parsed_data["ai_data"].get("abstract"):
                    ai_abstract = parsed_data["ai_data"]["abstract"]
                elif parsed_data.get("section_data") and parsed_data["section_data"].get("abstract"):
                    ai_abstract = parsed_data["section_data"]["abstract"]

                # 如果在线摘要太短（< 200字符），且AI摘要更长，使用AI摘要
                use_ai_abstract = False
                if online_abstract and len(online_abstract.strip()) < 200:
                    if ai_abstract and len(ai_abstract.strip()) > len(online_abstract.strip()):
                        use_ai_abstract = True
                        final_abstract = ai_abstract
                        logger.info(f"✅ AI摘要更长 ({len(ai_abstract)} 字符 > {len(online_abstract)} 字符)，使用AI摘要")
                    else:
                        final_abstract = online_abstract
                        logger.info(f"✅ 使用在线摘要 ({len(online_abstract)} 字符)")
                elif online_abstract and len(online_abstract.strip()) >= 200:
                    final_abstract = online_abstract
                    logger.info(f"✅ 使用在线摘要 ({len(online_abstract)} 字符)")
                else:
                    # 没有在线摘要，使用AI摘要
                    if ai_abstract:
                        use_ai_abstract = True
                        final_abstract = ai_abstract
                        logger.info(f"✅ 使用AI摘要 ({len(ai_abstract)} 字符)")
                    else:
                        final_abstract = ""

                # 更新所有摘要字段
                if final_abstract:
                    if "combined_metadata" in parsed_data:
                        parsed_data["combined_metadata"]["abstract"] = final_abstract
                    if "section_data" in parsed_data:
                        parsed_data["section_data"]["abstract"] = final_abstract
                    if "sections_json" in parsed_data.get("combined_metadata", {}):
                        parsed_data["combined_metadata"]["sections_json"]["abstract"] = final_abstract
            # ========== END ==========

            elapsed = time.time() - start_time
            logger.info(f"✅ 文献解析成功 ({elapsed:.2f}秒): {file_path.name}")
            
        except Exception as e:
            elapsed = time.time() - start_time
            error_msg = f"解析失败 ({elapsed:.2f}秒): {str(e)}"
            result["errors"].append(error_msg)
            logger.error(f"❌ {error_msg}")
        
        return result
    
    def _parse_pdf_file(self, pdf_path: Path, force_reparse: bool = False) -> Dict[str, Any]:
        """解析PDF文件"""
        start_time = time.time()
        
        # 1. 基础PDF解析
        pdf_data = self.pdf_parser.parse_pdf(pdf_path, force_reparse)
        
        # 2. 确保sections字段存在并完整
        if "sections" not in pdf_data:
            pdf_data["sections"] = {}
        
        sections = pdf_data["sections"]
        
        # 3. AI增强解析
        ai_data = {}
        logger.info(f"🤖 AI配置检查: AI_ENABLED={self.config.AI_ENABLED}, AI_EXTRACT_KEY_FINDINGS={getattr(self.config, 'AI_EXTRACT_KEY_FINDINGS', 'N/A')}")
        if self.config.AI_ENABLED:
            logger.info("🤖 开始AI增强解析...")
            ai_data = self.ai_parser.extract_with_ai(pdf_data)
            logger.info(f"🤖 AI解析完成, 返回数据: {list(ai_data.keys()) if ai_data else 'empty'}")
        
        # 4. 合并结果，按照优先级：在线 > AI > PDF
        combined_metadata = {}
        
        # 首先合并PDF元数据（最低优先级）
        if "metadata" in pdf_data:
            self._merge_metadata_with_priority(combined_metadata, pdf_data["metadata"], "pdf")
        
        # 然后合并AI元数据（中等优先级）
        if ai_data and "metadata" in ai_data:
            self._merge_metadata_with_priority(combined_metadata, ai_data["metadata"], "ai")
        
        # 5. 提取章节信息并准备存储
        section_data = {
            "abstract": sections.get("abstract", ""),
            "introduction": sections.get("introduction", ""),
            "methods": sections.get("methods", ""),
            "results": sections.get("results", ""),
            "discussion": sections.get("discussion", ""),
            "conclusions": sections.get("conclusions", ""),
            "data_availability": sections.get("data_availability", "")
        }
        
        # 构建完整的sections_json
        sections_json = {
            **section_data,
            "references": sections.get("references", ""),
            "full_text": pdf_data.get("text", "")  # 保存完整全文（用于RAG分块）
        }
        
        # 6. 提取并存储结构ID信息
        structure_info = pdf_data.get("structure_ids", {})
        
        # 构建完整的结构ID信息，包含提取的详细信息
        cryoem_targets = None
        if structure_info:
            cryoem_targets = {
                "pdb_ids": structure_info.get("pdb_ids", []),
                "emdb_ids": structure_info.get("emdb_ids", []),
                "pdb_contexts": structure_info.get("pdb_contexts", []),
                "emdb_contexts": structure_info.get("emdb_contexts", []),
                "data_availability_section_found": structure_info.get("data_availability_section_found", False),
                "extraction_method": structure_info.get("extraction_method", ""),
                "source_type": structure_info.get("source_type", ""),
                "preliminary_filtered": structure_info.get("preliminary_filtered", False),
                "filtering_status": structure_info.get("filtering_status", {})
            }
            
            # 记录提取结果
            pdb_count = len(structure_info.get("pdb_ids", []))
            emdb_count = len(structure_info.get("emdb_ids", []))
            logger.info(f"📊 提取到结构ID: PDB={pdb_count}, EMDB={emdb_count}")
            
            if structure_info.get("preliminary_filtered"):
                logger.info(f"📊 初步过滤已应用")
        
        # 7. 构建完整结果
        result = {
            "file_type": "pdf",
            "pdf_data": pdf_data,
            "ai_data": ai_data,
            "combined_metadata": combined_metadata,
            "section_data": section_data,
            "sections_json": sections_json,
            "structure_ids": cryoem_targets,  # 直接传递结构ID信息给structure_manager
            "text_chunks": []  # 用于向量化 chunks
        }

        # ========== 新增: 生成500字符chunks用于向量化 ==========
        full_text = pdf_data.get("text", "") or ""
        if full_text:
            chunk_size = 500
            chunks = []
            for i in range(0, len(full_text), chunk_size):
                chunk = full_text[i:i+chunk_size]
                if len(chunk) >= 50:  # 忽略太短的chunks
                    chunks.append({
                        "text": chunk,
                        "start_pos": i,
                        "end_pos": i + len(chunk),
                        "chunk_index": len(chunks)
                    })
            result["text_chunks"] = chunks
            logger.info(f"📝 生成了 {len(chunks)} 个 {chunk_size} 字符的chunks用于向量化")
        # ========== END ==========

        # 注意：在线摘要优先逻辑在 parse_literature_file 函数中处理（在线元数据后获取）
        # 此处使用PDF/AI提取的摘要作为后备
        combined_metadata["abstract"] = section_data["abstract"]

        combined_metadata["sections_json"] = sections_json
        combined_metadata["introduction"] = section_data["introduction"]
        combined_metadata["methods"] = section_data["methods"]
        combined_metadata["results"] = section_data["results"]
        combined_metadata["discussion"] = section_data["discussion"]
        combined_metadata["conclusions"] = section_data["conclusions"]
        combined_metadata["data_availability"] = section_data["data_availability"]
        combined_metadata["text_chunks"] = result["text_chunks"]  # 添加chunks到元数据


        # ========== 新增: 确保key_findings被保存 ==========
        # 从ai_data中提取key_findings并添加到result
        if ai_data and ai_data.get("key_findings"):
            result["key_findings"] = ai_data["key_findings"]
            combined_metadata["key_findings"] = ai_data["key_findings"]
            logger.info(f"✅ 添加了 {len(ai_data['key_findings'])} 个关键发现")
        # ========== END ==========

        elapsed = time.time() - start_time
        logger.info(f"✅ PDF文件解析完成 ({elapsed:.2f}秒)")

        return result
    
    def _parse_docx_file(self, docx_path: Path) -> Dict[str, Any]:
        """解析DOCX文件"""
        try:
            import docx2txt
            
            text = docx2txt.process(str(docx_path))
            
            # 提取结构ID - 使用最新的提取器
            structure_ids = {}
            if self.config.EXTRACT_STRUCTURE_IDS:
                extractor = StructureIDExtractor(self.config)
                # 直接使用文本进行提取
                structure_ids = extractor.extract_structure_ids(text)
            
            # 提取章节信息
            sections = self.pdf_parser._extract_sections_by_patterns(text)
            section_data = {
                "abstract": sections.get("abstract", ""),
                "introduction": sections.get("introduction", ""),
                "methods": sections.get("methods", ""),
                "results": sections.get("results", ""),
                "discussion": sections.get("discussion", ""),
                "conclusions": sections.get("conclusions", ""),
                "data_availability": sections.get("data_availability", "")
            }
            
            # 构建完整的sections_json
            sections_json = {
                **section_data,
                "references": sections.get("references", ""),
                "full_text": text  # 保存完整全文
            }
            
            # 构建元数据（最低优先级）
            combined_metadata = {
                "title": docx_path.stem,
                "extracted_text_length": len(text),
                **section_data,
                "sections_json": sections_json
            }
            
            # AI解析
            ai_data = {}
            if self.config.AI_ENABLED:
                ai_data = self.ai_parser.extract_with_ai({"text": text})
                if ai_data and "metadata" in ai_data:
                    # 合并AI元数据（中等优先级）
                    self._merge_metadata_with_priority(combined_metadata, ai_data["metadata"], "ai")
            
            result = {
                "file_type": "docx",
                "text": text,
                "ai_data": ai_data,
                "combined_metadata": combined_metadata,
                "section_data": section_data,
                "sections_json": sections_json,
                "structure_ids": structure_ids  # 直接传递结构ID信息给structure_manager
            }
            
            return result
            
        except Exception as e:
            logger.error(f"DOCX解析失败: {e}")
            raise
    
    def _parse_text_file(self, txt_path: Path) -> Dict[str, Any]:
        """解析文本文件"""
        try:
            with open(txt_path, 'r', encoding='utf-8') as f:
                text = f.read()
            
            # 提取结构ID - 使用最新的提取器
            structure_ids = {}
            if self.config.EXTRACT_STRUCTURE_IDS:
                extractor = StructureIDExtractor(self.config)
                # 直接使用文本进行提取
                structure_ids = extractor.extract_structure_ids(text)
            
            # 提取章节信息
            sections = self.pdf_parser._extract_sections_by_patterns(text)
            section_data = {
                "abstract": sections.get("abstract", ""),
                "introduction": sections.get("introduction", ""),
                "methods": sections.get("methods", ""),
                "results": sections.get("results", ""),
                "discussion": sections.get("discussion", ""),
                "conclusions": sections.get("conclusions", ""),
                "data_availability": sections.get("data_availability", "")
            }
            
            # 构建完整的sections_json
            sections_json = {
                **section_data,
                "references": sections.get("references", ""),
                "full_text": text  # 保存完整全文
            }
            
            # 构建元数据（最低优先级）
            combined_metadata = {
                "title": txt_path.stem,
                "extracted_text_length": len(text),
                **section_data,
                "sections_json": sections_json
            }
            
            # AI解析
            ai_data = {}
            if self.config.AI_ENABLED:
                ai_data = self.ai_parser.extract_with_ai({"text": text})
                if ai_data and "metadata" in ai_data:
                    # 合并AI元数据（中等优先级）
                    self._merge_metadata_with_priority(combined_metadata, ai_data["metadata"], "ai")
            
            result = {
                "file_type": "text",
                "text": text,
                "ai_data": ai_data,
                "combined_metadata": combined_metadata,
                "section_data": section_data,
                "sections_json": sections_json,
                "structure_ids": structure_ids  # 直接传递结构ID信息给structure_manager
            }
            
            return result
            
        except Exception as e:
            logger.error(f"文本文件解析失败: {e}")
            raise
    
    def _parse_bibtex_file(self, bib_path: Path) -> Dict[str, Any]:
        """解析BibTeX文件"""
        try:
            with open(bib_path, 'r', encoding='utf-8') as f:
                bib_content = f.read()
            
            parser = bibtexparser.bparser.BibTexParser(common_strings=True)
            bib_database = bibtexparser.loads(bib_content, parser=parser)
            
            entries = []
            for entry in bib_database.entries:
                entries.append({
                    "entry_type": entry.get('ENTRYTYPE', ''),
                    "citation_key": entry.get('ID', ''),
                    "title": entry.get('title', ''),
                    "author": entry.get('author', ''),
                    "year": entry.get('year', ''),
                    "journal": entry.get('journal', ''),
                    "doi": entry.get('doi', ''),
                    "url": entry.get('url', '')
                })
            
            result = {
                "file_type": "bibtex",
                "entries": entries,
                "entry_count": len(entries),
                "combined_metadata": {
                    "title": bib_path.stem,
                    "source": "bibtex"
                }
            }
            
            return result
            
        except Exception as e:
            logger.error(f"BibTeX解析失败: {e}")
            raise
    
    def _merge_metadata_with_priority(self, target: Dict[str, Any], source: Dict[str, Any], source_type: str) -> None:
        """
        按照优先级合并元数据
        
        Args:
            target: 目标字典（将被更新）
            source: 源字典
            source_type: 数据来源类型（"online", "ai", "pdf"）
        """
        if not source:
            return
        
        # 确定当前源在优先级列表中的位置
        try:
            source_priority = self.config.METADATA_PRIORITY_ORDER.index(source_type)
        except ValueError:
            # 如果不在优先级列表中，则使用最低优先级
            source_priority = len(self.config.METADATA_PRIORITY_ORDER)
        
        # 对于每个字段，检查是否应该更新
        for key, value in source.items():
            if value is None or value == "":
                continue
                
            # 检查目标中是否已有该字段
            if key in target:
                # 获取当前字段的源类型（如果有）
                current_source_type = target.get(f"{key}_source", "unknown")
                try:
                    current_priority = self.config.METADATA_PRIORITY_ORDER.index(current_source_type)
                except ValueError:
                    current_priority = len(self.config.METADATA_PRIORITY_ORDER)
                
                # 如果新源的优先级更高，则更新
                if source_priority < current_priority:
                    target[key] = value
                    target[f"{key}_source"] = source_type
                    logger.debug(f"📝 更新字段 '{key}': {source_type} (优先级{source_priority}) 覆盖 {current_source_type} (优先级{current_priority})")
            else:
                # 如果字段不存在，直接添加
                target[key] = value
                target[f"{key}_source"] = source_type
                logger.debug(f"📝 添加字段 '{key}' 来自 {source_type}")
    
    def _calculate_file_hash(self, file_path: Path) -> str:
        """计算文件哈希"""
        with open(file_path, 'rb') as f:
            return hashlib.md5(f.read()).hexdigest()
    
    def batch_parse_files(self, file_paths: List[Union[str, Path]]) -> List[Dict[str, Any]]:
        """批量解析文件"""
        results = []
        
        try:
            import concurrent.futures
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=self.config.MAX_WORKERS) as executor:
                future_to_file = {
                    executor.submit(self.parse_literature_file, file_path): file_path
                    for file_path in file_paths
                }
                
                for future in concurrent.futures.as_completed(future_to_file):
                    file_path = future_to_file[future]
                    try:
                        result = future.result(timeout=self.config.TIMEOUT_SECONDS)
                        results.append(result)
                    except Exception as e:
                        logger.error(f"批量解析失败 {file_path}: {e}")
                        results.append({
                            "success": False,
                            "file_path": str(file_path),
                            "error": str(e)
                        })
        except ImportError:
            # 如果没有concurrent.futures，顺序处理
            logger.warning("concurrent.futures不可用，将顺序处理文件")
            for file_path in file_paths:
                try:
                    result = self.parse_literature_file(file_path)
                    results.append(result)
                except Exception as e:
                    logger.error(f"批量解析失败 {file_path}: {e}")
                    results.append({
                        "success": False,
                        "file_path": str(file_path),
                        "error": str(e)
                    })
        
        return results

# ---------- 适配器函数 ----------
def extract_structured_literature_info(text: str) -> Dict[str, Any]:
    """
    提取结构化文献信息的适配器函数
    兼容旧的调用方式
    """
    try:
        result = parse_text_with_llm(text)
        
        # 转换为旧格式（如果需要）
        if result:
            return {
                "success": True,
                "metadata": {
                    "title": result.get("title", ""),
                    "authors": result.get("authors", []),
                    "journal": result.get("journal", ""),
                    "publication_date": result.get("publication_date", ""),
                    "year": result.get("year"),
                    "doi": result.get("doi", ""),
                    "keywords": result.get("keywords", []),
                    "abstract": result.get("abstract", "")
                },
                "key_findings": result.get("key_findings", []),
                "parsed_at": result.get("parsed_at")
            }
        
    except Exception as e:
        logger.error(f"提取文献信息失败: {e}")
    
    return {
        "success": False,
        "metadata": {},
        "key_findings": []
    }