const fileInput = document.querySelector('#fileInput');
const zone = document.querySelector('#dropzone');
const convertButton = document.querySelector('#convertButton');
const result = document.querySelector('#result');
const categorySelect = document.querySelector('#categorySelect');
const outputSelect = document.querySelector('#outputFormat');
const mediaUrl = document.querySelector('#mediaUrl');
const mediaInfo = document.querySelector('#mediaInfo');
const mediaControls = document.querySelector('#mediaControls');
const mediaMessage = document.querySelector('#mediaMessage');
const supportedPlatforms = document.querySelector('#supportedPlatforms');
const platformSearch = document.querySelector('#platformSearch');
const platformCount = document.querySelector('#platformCount');
const platformItems = document.querySelector('#platformItems');
let selectedFile = null;
let capabilities = null;
let resultUrl = null;
let supportedExtractors = null;
let extractorVersion = '';

const extOf = name => (name.split('.').pop() || '').toLowerCase();
const niceSize = bytes => bytes < 1024 * 1024 ? `${(bytes / 1024).toFixed(0)} كيلوبايت` : `${(bytes / 1024 / 1024).toFixed(1)} ميغابايت`;
const category = () => capabilities?.conversions.find(item => item.category === categorySelect.value);

function showResult(message, error = false, action = null) {
  result.replaceChildren();
  result.className = error ? 'result error' : 'result';
  result.hidden = false;
  result.append(document.createTextNode(message));
  if (action) result.append(action);
}
function clearResult() {
  if (resultUrl) URL.revokeObjectURL(resultUrl);
  resultUrl = null;
  result.hidden = true;
  result.replaceChildren();
}
function renderOutputs() {
  const item = category();
  outputSelect.replaceChildren();
  const sourceExt = selectedFile ? extOf(selectedFile.name) : '';
  for (const ext of item?.outputs || []) {
    if (ext === sourceExt) continue;
    const option = document.createElement('option');
    option.value = ext;
    option.textContent = ext.toUpperCase();
    outputSelect.append(option);
  }
  outputSelect.disabled = !item?.available || !item.outputs.length;
  const suffixes = item?.inputs || [];
  fileInput.accept = suffixes.map(ext => `.${ext}`).join(',');
  document.querySelector('#supportedHint').textContent = suffixes.map(ext => ext.toUpperCase()).join(' · ') || 'لا توجد صيغ متاحة لهذا النوع';
  document.querySelector('#capabilityNote').innerHTML = item?.available
    ? '<span>◈</span> تُعالج الملفات على الخادم وتُحذف بعد تنزيل النتيجة'
    : `<span>◈</span> ${item?.reason || 'محرك التحويل غير متاح على الخادم'}`;
  if (selectedFile) validateSelectedFile();
}
function validateSelectedFile() {
  if (!selectedFile) return;
  const item = category();
  if (!item?.inputs.includes(extOf(selectedFile.name))) {
    selectedFile = null;
    fileInput.value = '';
    convertButton.disabled = true;
    document.querySelector('#fileName').textContent = 'صيغة الملف لا تطابق النوع المحدد';
    document.querySelector('#fileMeta').textContent = 'اختر نوع الملف المناسب أو غيّر التصنيف';
    document.querySelector('#removeFile').hidden = true;
    showResult('امتداد الملف لا يطابق نوع التحويل المختار.', true);
    return;
  }
  convertButton.disabled = !item.available || !outputSelect.value;
}
function setFile(file) {
  clearResult();
  if (!file) return;
  const item = category();
  if (!item?.inputs.includes(extOf(file.name))) {
    selectedFile = null;
    fileInput.value = '';
    convertButton.disabled = true;
    document.querySelector('#fileName').textContent = 'صيغة غير مدعومة لهذا النوع';
    document.querySelector('#fileMeta').textContent = 'اختر نوع التحويل المناسب للملف';
    document.querySelector('#removeFile').hidden = true;
    showResult('هذا الامتداد غير موجود ضمن صيغ الإدخال لهذا النوع.', true);
    return;
  }
  if (file.size > capabilities.maxUploadBytes) {
    selectedFile = null;
    fileInput.value = '';
    convertButton.disabled = true;
    document.querySelector('#fileName').textContent = 'الملف يتجاوز الحد المسموح';
    document.querySelector('#fileMeta').textContent = 'اختر ملفًا أصغر من 150 ميغابايت';
    document.querySelector('#removeFile').hidden = true;
    showResult(`الحد الأقصى لحجم الملف هو ${niceSize(capabilities.maxUploadBytes)}.`, true);
    return;
  }
  selectedFile = file;
  document.querySelector('#fileName').textContent = file.name;
  document.querySelector('#fileMeta').textContent = `${extOf(file.name).toUpperCase()} · ${niceSize(file.size)}`;
  document.querySelector('#dropTitle').textContent = 'الملف جاهز للتحويل';
  document.querySelector('#dropSubtitle').textContent = file.name;
  document.querySelector('#removeFile').hidden = false;
  validateSelectedFile();
}
function removeFile() {
  selectedFile = null;
  fileInput.value = '';
  clearResult();
  convertButton.disabled = true;
  document.querySelector('#fileName').textContent = 'لم يتم اختيار ملف';
  document.querySelector('#fileMeta').textContent = 'اختر نوع الملف للبدء';
  document.querySelector('#dropTitle').textContent = 'اسحب الملف إلى هنا';
  document.querySelector('#dropSubtitle').innerHTML = 'أو <button class="text-button" id="browseButton" type="button">اختر ملفًا</button> من جهازك';
  document.querySelector('#browseButton').addEventListener('click', () => fileInput.click());
  document.querySelector('#removeFile').hidden = true;
}
async function loadCapabilities() {
  try {
    const response = await fetch('/api/capabilities');
    if (!response.ok) throw new Error('capabilities');
    capabilities = await response.json();
    categorySelect.replaceChildren();
    for (const item of capabilities.conversions) {
      const option = document.createElement('option');
      option.value = item.category;
      option.textContent = `${item.label}${item.available ? '' : ' · غير متاح'}`;
      option.disabled = !item.available;
      categorySelect.append(option);
    }
    const first = capabilities.conversions.find(item => item.available);
    if (first) categorySelect.value = first.category;
    else showResult('لم يعثر الخادم على محركات تحويل متاحة.', true);
    if (!capabilities.mediaDownload?.available) {
      document.querySelector('#inspectButton').disabled = true;
      mediaUrl.disabled = true;
      setMediaMessage('محرك تنزيل الوسائط غير متاح على الخادم.');
    }
    renderOutputs();
  } catch {
    document.querySelector('#supportedHint').textContent = 'تعذر الاتصال بخادم التحويل';
    showResult('تعذر تحميل قدرات الخادم. أعد تشغيل الموقع وحاول مجددًا.', true);
  }
}

document.querySelector('#browseButton').addEventListener('click', () => fileInput.click());
zone.addEventListener('click', event => { if (!event.target.closest('button')) fileInput.click(); });
zone.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); fileInput.click(); } });
fileInput.addEventListener('change', () => setFile(fileInput.files[0]));
document.querySelector('#removeFile').addEventListener('click', removeFile);
categorySelect.addEventListener('change', () => { clearResult(); renderOutputs(); });
for (const name of ['dragenter', 'dragover']) zone.addEventListener(name, event => { event.preventDefault(); zone.classList.add('dragover'); });
for (const name of ['dragleave', 'drop']) zone.addEventListener(name, event => { event.preventDefault(); zone.classList.remove('dragover'); });
zone.addEventListener('drop', event => setFile(event.dataTransfer.files[0]));

convertButton.addEventListener('click', async () => {
  if (!selectedFile || !category()?.available || !outputSelect.value) return;
  convertButton.disabled = true;
  convertButton.textContent = 'جارٍ التحويل الفعلي…';
  clearResult();
  try {
    const body = new FormData();
    body.append('file', selectedFile);
    body.append('target', outputSelect.value);
    const response = await fetch('/api/convert', { method: 'POST', body });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.detail || 'تعذر تحويل الملف.');
    }
    const blob = await response.blob();
    if (!blob.size) throw new Error('لم ينتج المحول ملفًا صالحًا.');
    const disposition = response.headers.get('content-disposition') || '';
    const nameMatch = disposition.match(/filename="?([^";]+)"?/i);
    const fallback = `${selectedFile.name.replace(/\.[^.]+$/, '')}.${outputSelect.value}`;
    const filename = nameMatch ? decodeURIComponent(nameMatch[1]) : fallback;
    resultUrl = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = resultUrl; link.download = filename; link.textContent = 'تنزيل النتيجة';
    showResult(`اكتمل التحويل · ${niceSize(blob.size)}`, false, link);
  } catch (error) {
    showResult(error.message || 'تعذر تحويل الملف.', true);
  } finally {
    convertButton.disabled = !selectedFile || !category()?.available || !outputSelect.value;
    convertButton.innerHTML = 'تحويل الملف <span>↗</span>';
  }
});

function durationText(seconds) {
  if (!seconds) return 'المدة غير متاحة';
  const total = Math.round(seconds);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')} دقيقة`;
}
function setMediaMessage(text, error = false) {
  mediaMessage.textContent = text;
  mediaMessage.classList.toggle('error-text', error);
}
function renderSupportedPlatforms() {
  if (!supportedExtractors) return;
  const query = platformSearch.value.trim().toLocaleLowerCase();
  if (!query) {
    platformItems.replaceChildren();
    platformItems.hidden = true;
    platformCount.textContent = `اكتب اسم منصة لعرض النتائج · ${supportedExtractors.length} مستخرجًا في إصدار yt-dlp ${extractorVersion}`;
    return;
  }
  const matches = supportedExtractors.filter(name => name.toLocaleLowerCase().includes(query));
  platformItems.hidden = false;
  platformItems.replaceChildren();
  const fragment = document.createDocumentFragment();
  for (const name of matches) {
    const item = document.createElement('li');
    item.textContent = name;
    fragment.append(item);
  }
  platformItems.append(fragment);
  platformCount.textContent = query
    ? `${matches.length} نتيجة من أصل ${supportedExtractors.length}`
    : `${supportedExtractors.length} مستخرجًا · إصدار yt-dlp ${extractorVersion}`;
}
async function loadSupportedPlatforms() {
  if (supportedExtractors) return;
  platformCount.textContent = 'جارٍ تحميل القائمة...';
  try {
    const response = await fetch('/api/media/platforms');
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || 'تعذر تحميل قائمة المنصات.');
    supportedExtractors = data.extractors || [];
    extractorVersion = data.version || 'غير معروف';
    renderSupportedPlatforms();
  } catch (error) {
    platformCount.textContent = error.message || 'تعذر تحميل قائمة المنصات.';
  }
}
supportedPlatforms.addEventListener('toggle', () => {
  if (supportedPlatforms.open) loadSupportedPlatforms();
});
platformSearch.addEventListener('input', renderSupportedPlatforms);
if (supportedPlatforms.open) loadSupportedPlatforms();
document.querySelector('#inspectButton').addEventListener('click', async () => {
  const url = mediaUrl.value.trim();
  if (!url) { setMediaMessage('أدخل رابطًا أولًا.', true); return; }
  const button = document.querySelector('#inspectButton');
  button.disabled = true; button.textContent = 'جارٍ فحص الرابط…';
  mediaControls.hidden = true; mediaInfo.hidden = true; setMediaMessage('');
  try {
    const response = await fetch('/api/media/info', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url }) });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || 'تعذر فحص الرابط.');
    const qualities = document.querySelector('#mediaQuality');
    qualities.replaceChildren(new Option('أفضل جودة متاحة', 'best'));
    for (const quality of data.qualities || []) qualities.append(new Option(quality, quality.replace(/p$/, '')));
    mediaInfo.textContent = `${data.title} · ${data.extractor} · ${durationText(data.duration)}`;
    mediaInfo.hidden = false; mediaControls.hidden = false;
    setMediaMessage('تم استخراج معلومات الوسيط. اختر الصيغة والجودة ثم نزّل الملف.');
  } catch (error) {
    setMediaMessage(error.message || 'تعذر فحص الرابط.', true);
  } finally {
    button.disabled = false; button.innerHTML = 'فحص الرابط <span>⌕</span>';
  }
});
document.querySelector('#mediaMode').addEventListener('change', event => {
  const isAudio = event.target.value === 'audio';
  document.querySelector('#qualityWrap').hidden = isAudio;
  const format = document.querySelector('#mediaFormat');
  format.replaceChildren(...(isAudio ? ['mp3', 'm4a', 'aac', 'wav', 'flac', 'opus', 'ogg'] : ['mp4', 'mkv', 'webm']).map(ext => new Option(ext.toUpperCase(), ext)));
});
document.querySelector('#downloadButton').addEventListener('click', async () => {
  const button = document.querySelector('#downloadButton');
  button.disabled = true; button.textContent = 'جارٍ التنزيل والتحويل…';
  setMediaMessage('العملية جارية على الخادم. قد يستغرق ذلك بعض الوقت.');
  try {
    const form = new FormData();
    form.append('url', mediaUrl.value.trim());
    form.append('mode', document.querySelector('#mediaMode').value);
    form.append('quality', document.querySelector('#mediaQuality').value);
    form.append('output_format', document.querySelector('#mediaFormat').value);
    const response = await fetch('/api/media/download', { method: 'POST', body: form });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.detail || 'تعذر تنزيل الوسيط.');
    }
    const blob = await response.blob();
    if (!blob.size) throw new Error('لم ينتج التنزيل ملفًا صالحًا.');
    const disposition = response.headers.get('content-disposition') || '';
    const match = disposition.match(/filename="?([^";]+)"?/i);
    const filename = match ? decodeURIComponent(match[1]) : `openConvert.${document.querySelector('#mediaFormat').value}`;
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a'); link.href = url; link.download = filename; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 30_000);
    setMediaMessage(`اكتمل التنزيل والتحقق من الملف · ${niceSize(blob.size)}`);
  } catch (error) {
    setMediaMessage(error.message || 'تعذر تنزيل الوسيط.', true);
  } finally {
    button.disabled = false; button.innerHTML = 'تنزيل الملف <span>↓</span>';
  }
});

const themeToggle = document.querySelector('#themeToggle');
const themeToggleText = document.querySelector('#themeToggleText');
function applyTheme(theme, persist = true) {
  const light = theme === 'light';
  document.body.dataset.theme = light ? 'light' : 'dark';
  themeToggle.setAttribute('aria-pressed', String(light));
  themeToggle.setAttribute('aria-label', light ? 'التبديل إلى الوضع الأسود' : 'التبديل إلى الوضع الأبيض');
  themeToggleText.textContent = light ? 'الوضع الأسود' : 'الوضع الأبيض';
  document.querySelector('meta[name="theme-color"]').content = light ? '#f6f6f4' : '#111111';
  if (persist) {
    try { localStorage.setItem('openConvertTheme', light ? 'light' : 'dark'); } catch {}
  }
}
try {
  if (localStorage.getItem('openConvertTheme') === 'light' || localStorage.getItem('openDownloadTheme') === 'light') applyTheme('light', false);
} catch {}
themeToggle.addEventListener('click', () => {
  applyTheme(document.body.dataset.theme === 'light' ? 'dark' : 'light');
});

loadCapabilities();
