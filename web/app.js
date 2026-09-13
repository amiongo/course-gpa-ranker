// 全局常量与状态
const browserClientId = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
let heartbeatTimer = null;

// 视图切换元素
const navTabs = document.querySelectorAll('.nav-tab');
const viewPanels = document.querySelectorAll('.view-panel');

// 课程表时间状态 (7 天 x 13 节，全部默认为 true: 允许上课)
// 索引：day 0..6 (周一至周日)，period 0..12 (第1至13节)
const timetableState = Array.from({ length: 7 }, () => Array(13).fill(true));

const PERIOD_TIMES = [
  '08:00-08:45', '08:50-09:35', '10:00-10:45', '10:50-11:35', '11:40-12:25',
  '13:15-14:00', '14:05-14:50', '14:55-15:40', '15:50-16:35', '16:40-17:25',
  '18:30-19:15', '19:20-20:05', '20:10-20:55',
];

const DAYS_NAMES = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'];

// 筛选状态
let categoryHierarchyData = null;
let currentL1 = '';
let currentL2 = '';
let currentMinSamples = null;
let currentMinGpa = null;
let currentKeyword = '';
let currentExcludeKeyword = '';
let currentPage = 1;
let currentPageSize = 20;

// 课表拖拽选区状态
let isPointerDown = false;
let dragTargetState = true;

// DOM 元素引用
const categoryL1Container = document.querySelector('#category-l1-container');
const categoryL2Container = document.querySelector('#category-l2-container');
const catTotalCount = document.querySelector('#cat-total-count');
const timetableBody = document.querySelector('#timetable-body');
const ttSelectedCount = document.querySelector('#tt-selected-count');
const minSamplesInput = document.querySelector('#min-samples-input');
const samplePills = document.querySelectorAll('.sample-pill');
const minGpaInput = document.querySelector('#min-gpa-input');
const gpaPills = document.querySelectorAll('.gpa-pill');
const filterKeywordInput = document.querySelector('#filter-keyword-input');
const filterExcludeInput = document.querySelector('#filter-exclude-input');
const excludePills = document.querySelectorAll('.exclude-pill');
const applyFilterBtn = document.querySelector('#apply-filter-btn');
const resetFilterBtn = document.querySelector('#reset-filter-btn');
const filterSummaryText = document.querySelector('#filter-summary-text');
const pageSizeSelect = document.querySelector('#page-size-select');
const filterCoursesContainer = document.querySelector('#filter-courses-container');
const filterPagination = document.querySelector('#filter-pagination');
const pagePrevBtn = document.querySelector('#page-prev');
const pageNextBtn = document.querySelector('#page-next');
const pageIndicator = document.querySelector('#page-indicator');

// 既有搜索/批量元素引用
const searchForm = document.querySelector('#search-form');
const searchInput = document.querySelector('#search-input');
const searchResults = document.querySelector('#search-results');
const planInput = document.querySelector('#plan-input');
const batchButton = document.querySelector('#batch-rank');
const batchStatus = document.querySelector('#batch-status');
const batchResults = document.querySelector('#batch-results');

// ====================== 心跳与基础请求 ======================
function sendBrowserSignal(disconnect = false) {
  const payload = JSON.stringify({ client_id: browserClientId });
  const endpoint = disconnect ? '/api/disconnect' : '/api/heartbeat';
  if (disconnect && navigator.sendBeacon) {
    navigator.sendBeacon(endpoint, new Blob([payload], { type: 'application/json' }));
    return;
  }
  fetch(endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: payload,
    keepalive: disconnect,
  }).catch(() => {});
}

function startBrowserHeartbeat() {
  if (heartbeatTimer !== null) return;
  sendBrowserSignal();
  heartbeatTimer = setInterval(() => sendBrowserSignal(), 2000);
}

function stopBrowserHeartbeat() {
  if (heartbeatTimer === null) return;
  clearInterval(heartbeatTimer);
  heartbeatTimer = null;
  sendBrowserSignal(true);
}

startBrowserHeartbeat();
window.addEventListener('pageshow', startBrowserHeartbeat);
window.addEventListener('pagehide', stopBrowserHeartbeat);

async function request(url, options) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || '请求失败');
  return data;
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
  }[char]));
}

function courseLabel(course) {
  return course.code ? `${course.name} (${course.code})` : course.name;
}

// ====================== 选项卡切换 ======================
navTabs.forEach(tab => {
  tab.addEventListener('click', () => {
    const targetId = tab.dataset.target;
    navTabs.forEach(t => {
      t.classList.toggle('active', t === tab);
      t.setAttribute('aria-selected', t === tab ? 'true' : 'false');
    });
    viewPanels.forEach(panel => {
      const isTarget = panel.id === targetId;
      panel.classList.toggle('active', isTarget);
      panel.hidden = !isTarget;
    });
  });
});

// ====================== 7x13 课程表交互 ======================
function renderTimetableGrid() {
  timetableBody.innerHTML = '';
  for (let period = 1; period <= 13; period++) {
    const tr = document.createElement('tr');
    if (period === 5) tr.classList.add('period-morning-end');
    if (period === 10) tr.classList.add('period-afternoon-end');

    // 行头：节次与时段
    const th = document.createElement('th');
    th.className = 'row-header';
    th.dataset.period = period;
    th.title = '点击全选/反选该节次所有星期';
    const periodName = period <= 5 ? `上午 第${period}节` : (period <= 10 ? `下午 第${period}节` : `晚上 第${period}节`);
    th.innerHTML = `${periodName} <span class="period-tag">${PERIOD_TIMES[period - 1]}</span>`;
    th.addEventListener('click', () => toggleRowPeriod(period));
    tr.appendChild(th);

    // 7 列单元格 (周一到周日)
    for (let day = 1; day <= 7; day++) {
      const td = document.createElement('td');
      td.className = 'tt-cell active';
      td.dataset.day = day;
      td.dataset.period = period;
      td.title = `${DAYS_NAMES[day - 1]} 第${period}节 (${PERIOD_TIMES[period - 1]})`;

      td.addEventListener('mousedown', (e) => {
        if (e.button !== 0) return;
        isPointerDown = true;
        dragTargetState = !timetableState[day - 1][period - 1];
        setCellState(day, period, dragTargetState);
      });

      td.addEventListener('mouseenter', () => {
        if (isPointerDown) {
          setCellState(day, period, dragTargetState);
        }
      });

      tr.appendChild(td);
    }

    timetableBody.appendChild(tr);
  }

  // 列表头点击：整天全选/反选
  document.querySelectorAll('.day-header').forEach(header => {
    header.addEventListener('click', () => {
      const day = parseInt(header.dataset.day, 10);
      toggleColDay(day);
    });
  });

  window.addEventListener('mouseup', () => {
    if (isPointerDown) {
      isPointerDown = false;
      fetchFilteredCourses(1);
    }
  });

  updateTimetableUI();
}

function setCellState(day, period, active) {
  timetableState[day - 1][period - 1] = active;
  const cell = timetableBody.querySelector(`[data-day="${day}"][data-period="${period}"]`);
  if (cell) {
    cell.classList.toggle('active', active);
    cell.classList.toggle('inactive', !active);
  }
  updateSelectedCount();
}

function toggleRowPeriod(period) {
  const currentActiveCount = timetableState.reduce((acc, col) => acc + (col[period - 1] ? 1 : 0), 0);
  const targetState = currentActiveCount < 7;
  for (let day = 1; day <= 7; day++) {
    timetableState[day - 1][period - 1] = targetState;
  }
  updateTimetableUI();
  fetchFilteredCourses(1);
}

function toggleColDay(day) {
  const currentActiveCount = timetableState[day - 1].filter(Boolean).length;
  const targetState = currentActiveCount < 13;
  for (let period = 1; period <= 13; period++) {
    timetableState[day - 1][period - 1] = targetState;
  }
  updateTimetableUI();
  fetchFilteredCourses(1);
}

function updateTimetableUI() {
  for (let day = 1; day <= 7; day++) {
    for (let period = 1; period <= 13; period++) {
      const active = timetableState[day - 1][period - 1];
      const cell = timetableBody.querySelector(`[data-day="${day}"][data-period="${period}"]`);
      if (cell) {
        cell.classList.toggle('active', active);
        cell.classList.toggle('inactive', !active);
      }
    }
  }
  updateSelectedCount();
}

function updateSelectedCount() {
  let count = 0;
  for (let day = 0; day < 7; day++) {
    for (let p = 0; p < 13; p++) {
      if (timetableState[day][p]) count++;
    }
  }
  ttSelectedCount.textContent = `已选 ${count} / 91 个时段`;
}

// 快捷操作按钮
document.querySelector('#tt-btn-all').addEventListener('click', () => {
  for (let d = 0; d < 7; d++) timetableState[d].fill(true);
  updateTimetableUI();
  fetchFilteredCourses(1);
});

document.querySelector('#tt-btn-clear').addEventListener('click', () => {
  for (let d = 0; d < 7; d++) timetableState[d].fill(false);
  updateTimetableUI();
  fetchFilteredCourses(1);
});

document.querySelector('#tt-btn-weekdays').addEventListener('click', () => {
  for (let d = 0; d < 5; d++) timetableState[d].fill(true);
  timetableState[5].fill(false);
  timetableState[6].fill(false);
  updateTimetableUI();
  fetchFilteredCourses(1);
});

document.querySelector('#tt-btn-morning').addEventListener('click', () => {
  for (let d = 0; d < 7; d++) {
    for (let p = 0; p < 13; p++) {
      timetableState[d][p] = p < 5;
    }
  }
  updateTimetableUI();
  fetchFilteredCourses(1);
});

document.querySelector('#tt-btn-afternoon').addEventListener('click', () => {
  for (let d = 0; d < 7; d++) {
    for (let p = 0; p < 13; p++) {
      timetableState[d][p] = p >= 5 && p < 10;
    }
  }
  updateTimetableUI();
  fetchFilteredCourses(1);
});

document.querySelector('#tt-btn-evening').addEventListener('click', () => {
  for (let d = 0; d < 7; d++) {
    for (let p = 0; p < 13; p++) {
      timetableState[d][p] = p >= 10;
    }
  }
  updateTimetableUI();
  fetchFilteredCourses(1);
});

document.querySelector('#tt-btn-no-early').addEventListener('click', () => {
  for (let d = 0; d < 7; d++) {
    timetableState[d][0] = false;
    timetableState[d][1] = false;
    for (let p = 2; p < 13; p++) timetableState[d][p] = true;
  }
  updateTimetableUI();
  fetchFilteredCourses(1);
});

document.querySelector('#tt-btn-invert').addEventListener('click', () => {
  for (let d = 0; d < 7; d++) {
    for (let p = 0; p < 13; p++) {
      timetableState[d][p] = !timetableState[d][p];
    }
  }
  updateTimetableUI();
  fetchFilteredCourses(1);
});

// ====================== 课程种类层级筛选 ======================
async function loadCategories() {
  try {
    const data = await request('/api/categories');
    categoryHierarchyData = data;
    catTotalCount.textContent = (data.total_courses || 0).toLocaleString();

    // 渲染一级大类按钮
    categoryL1Container.innerHTML = '';
    const allL1Btn = document.createElement('button');
    allL1Btn.type = 'button';
    allL1Btn.className = 'pill-btn active';
    allL1Btn.dataset.val = '';
    allL1Btn.innerHTML = `全部大类 (${(data.total_courses || 0).toLocaleString()})`;
    allL1Btn.addEventListener('click', () => selectL1(''));
    categoryL1Container.appendChild(allL1Btn);

    for (const [l1, l2List] of Object.entries(data.hierarchy || {})) {
      const count = data.counts?.[l1]?.total || 0;
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'pill-btn';
      btn.dataset.val = l1;
      btn.innerHTML = `${escapeHtml(l1)} (${count.toLocaleString()})`;
      btn.addEventListener('click', () => selectL1(l1));
      categoryL1Container.appendChild(btn);
    }

    renderL2Buttons();
  } catch (error) {
    console.error('加载课程种类层级失败:', error);
  }
}

function selectL1(l1) {
  if (currentL1 === l1) return;
  currentL1 = l1;
  currentL2 = ''; // 重置二级

  categoryL1Container.querySelectorAll('.pill-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.val === l1);
  });

  renderL2Buttons();
  fetchFilteredCourses(1);
}

function renderL2Buttons() {
  categoryL2Container.innerHTML = '';
  const allL2Btn = document.createElement('button');
  allL2Btn.type = 'button';
  allL2Btn.className = 'pill-btn active';
  allL2Btn.dataset.val = '';
  allL2Btn.textContent = '全部二级分类';
  allL2Btn.addEventListener('click', () => selectL2(''));
  categoryL2Container.appendChild(allL2Btn);

  if (!currentL1 || !categoryHierarchyData?.hierarchy?.[currentL1]) {
    return;
  }

  const subcats = categoryHierarchyData.hierarchy[currentL1] || [];
  const subCounts = categoryHierarchyData.counts?.[currentL1]?.subcategories || {};

  subcats.forEach(l2 => {
    const count = subCounts[l2] || 0;
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'pill-btn';
    btn.dataset.val = l2;
    btn.innerHTML = `${escapeHtml(l2)} (${count})`;
    btn.addEventListener('click', () => selectL2(l2));
    categoryL2Container.appendChild(btn);
  });
}

function selectL2(l2) {
  if (currentL2 === l2) return;
  currentL2 = l2;
  categoryL2Container.querySelectorAll('.pill-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.val === l2);
  });
  fetchFilteredCourses(1);
}

// ====================== 样本数量阈值与均绩门槛 ======================
samplePills.forEach(pill => {
  pill.addEventListener('click', () => {
    samplePills.forEach(p => p.classList.toggle('active', p === pill));
    const val = pill.dataset.samples;
    minSamplesInput.value = val;
    currentMinSamples = val ? parseInt(val, 10) : null;
    fetchFilteredCourses(1);
  });
});

minSamplesInput.addEventListener('input', () => {
  const val = minSamplesInput.value.trim();
  currentMinSamples = val ? parseInt(val, 10) : null;
  samplePills.forEach(p => p.classList.toggle('active', p.dataset.samples === val));
});

minSamplesInput.addEventListener('change', () => fetchFilteredCourses(1));

gpaPills.forEach(pill => {
  pill.addEventListener('click', () => {
    gpaPills.forEach(p => p.classList.toggle('active', p === pill));
    const val = pill.dataset.gpa;
    minGpaInput.value = val;
    currentMinGpa = val ? parseFloat(val) : null;
    fetchFilteredCourses(1);
  });
});

minGpaInput.addEventListener('input', () => {
  const val = minGpaInput.value.trim();
  currentMinGpa = val ? parseFloat(val) : null;
  gpaPills.forEach(p => p.classList.toggle('active', p.dataset.gpa === val));
});

minGpaInput.addEventListener('change', () => fetchFilteredCourses(1));

let filterInputDebounceTimer = null;
function triggerDebouncedFilter() {
  if (filterInputDebounceTimer) clearTimeout(filterInputDebounceTimer);
  filterInputDebounceTimer = setTimeout(() => {
    currentKeyword = filterKeywordInput.value.trim();
    currentExcludeKeyword = filterExcludeInput.value.trim();
    fetchFilteredCourses(1);
  }, 300);
}

filterKeywordInput.addEventListener('input', triggerDebouncedFilter);
filterKeywordInput.addEventListener('change', () => {
  currentKeyword = filterKeywordInput.value.trim();
  currentExcludeKeyword = filterExcludeInput.value.trim();
  fetchFilteredCourses(1);
});

filterKeywordInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') {
    e.preventDefault();
    if (filterInputDebounceTimer) clearTimeout(filterInputDebounceTimer);
    currentKeyword = filterKeywordInput.value.trim();
    currentExcludeKeyword = filterExcludeInput.value.trim();
    fetchFilteredCourses(1);
  }
});

filterExcludeInput.addEventListener('input', () => {
  const words = filterExcludeInput.value.trim().split(/[\s,，、]+/).filter(Boolean);
  excludePills.forEach(p => p.classList.toggle('active', words.includes(p.dataset.exclude)));
  triggerDebouncedFilter();
});

filterExcludeInput.addEventListener('change', () => {
  currentKeyword = filterKeywordInput.value.trim();
  currentExcludeKeyword = filterExcludeInput.value.trim();
  fetchFilteredCourses(1);
});

filterExcludeInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') {
    e.preventDefault();
    if (filterInputDebounceTimer) clearTimeout(filterInputDebounceTimer);
    currentKeyword = filterKeywordInput.value.trim();
    currentExcludeKeyword = filterExcludeInput.value.trim();
    fetchFilteredCourses(1);
  }
});

excludePills.forEach(pill => {
  pill.addEventListener('click', () => {
    const word = pill.dataset.exclude;
    let words = filterExcludeInput.value.trim().split(/[\s,，、]+/).filter(Boolean);
    const idx = words.indexOf(word);
    if (idx >= 0) {
      words.splice(idx, 1);
      pill.classList.remove('active');
    } else {
      words.push(word);
      pill.classList.add('active');
    }
    filterExcludeInput.value = words.join(' ');
    currentExcludeKeyword = filterExcludeInput.value.trim();
    currentKeyword = filterKeywordInput.value.trim();
    fetchFilteredCourses(1);
  });
});

applyFilterBtn.addEventListener('click', () => {
  currentKeyword = filterKeywordInput.value.trim();
  currentExcludeKeyword = filterExcludeInput.value.trim();
  fetchFilteredCourses(1);
});

resetFilterBtn.addEventListener('click', () => {
  for (let d = 0; d < 7; d++) timetableState[d].fill(true);
  updateTimetableUI();
  currentL1 = '';
  currentL2 = '';
  categoryL1Container.querySelectorAll('.pill-btn').forEach(b => b.classList.toggle('active', b.dataset.val === ''));
  renderL2Buttons();

  currentMinSamples = null;
  minSamplesInput.value = '';
  samplePills.forEach(p => p.classList.toggle('active', p.dataset.samples === ''));

  currentMinGpa = null;
  minGpaInput.value = '';
  gpaPills.forEach(p => p.classList.toggle('active', p.dataset.gpa === ''));

  currentKeyword = '';
  filterKeywordInput.value = '';
  currentExcludeKeyword = '';
  filterExcludeInput.value = '';
  excludePills.forEach(p => p.classList.remove('active'));

  fetchFilteredCourses(1);
});

pageSizeSelect.addEventListener('change', () => {
  currentPageSize = parseInt(pageSizeSelect.value, 10) || 20;
  fetchFilteredCourses(1);
});

// ====================== 核心筛选与排序请求 ======================
async function fetchFilteredCourses(page = 1) {
  currentPage = page;
  filterCoursesContainer.innerHTML = '<p class="status-text">正在依据课表时段与分类综合筛选课程...</p>';

  // 提取已选时段
  const selectedSlots = [];
  for (let day = 1; day <= 7; day++) {
    for (let period = 1; period <= 13; period++) {
      if (timetableState[day - 1][period - 1]) {
        selectedSlots.push([day, period]);
      }
    }
  }

  const payload = {
    selected_slots: selectedSlots,
    category_l1: currentL1,
    category_l2: currentL2,
    min_samples: currentMinSamples,
    min_gpa: currentMinGpa,
    q: currentKeyword,
    exclude_q: currentExcludeKeyword,
    page: currentPage,
    page_size: currentPageSize,
  };

  try {
    const data = await request('/api/filter', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    renderFilterResults(data);
  } catch (error) {
    filterCoursesContainer.innerHTML = `<p class="error">${escapeHtml(error.message)}</p>`;
  }
}

function renderFilterResults(data) {
  const totalCourses = data.total_courses || 0;
  const totalClasses = data.total_classes || 0;
  const courses = data.courses || [];
  const totalPages = data.total_pages || 1;

  filterSummaryText.textContent = `共筛选出 ${totalCourses.toLocaleString()} 门课程，剩余 ${totalClasses.toLocaleString()} 个合格教学班（按所剩教学班最高均绩降序排列）`;

  if (!courses.length) {
    filterCoursesContainer.innerHTML = `
      <div class="course-result" style="padding: 28px; text-align: center;">
        <p style="font-size: 16px; font-weight: 600; color: #475569; margin: 0 0 6px;">没有找到符合当前筛选条件的课程与教学班</p>
        <p class="hint">请尝试放宽课程表可选时段、调整样本数量阈值或清空分类筛选条件。</p>
      </div>`;
    filterPagination.hidden = true;
    return;
  }

  filterCoursesContainer.innerHTML = '';
  courses.forEach(course => {
    filterCoursesContainer.appendChild(createFilteredCourseCard(course));
  });

  // 分页控制
  filterPagination.hidden = totalPages <= 1;
  pageIndicator.textContent = `第 ${data.page} / ${totalPages} 页`;
  pagePrevBtn.disabled = data.page <= 1;
  pageNextBtn.disabled = data.page >= totalPages;

  pagePrevBtn.onclick = () => {
    if (currentPage > 1) fetchFilteredCourses(currentPage - 1);
  };
  pageNextBtn.onclick = () => {
    if (currentPage < totalPages) fetchFilteredCourses(currentPage + 1);
  };
}

function createFilteredCourseCard(course) {
  const article = document.createElement('article');
  article.className = 'course-result';

  const summary = document.createElement('div');
  summary.className = 'course-summary';

  const maxGpaText = course.max_gpa !== null ? course.max_gpa.toFixed(2) : '暂无数据';
  const categoryText = course.category_l1 ? `${course.category_l1} · ${course.category_l2}` : '未分类';

  summary.innerHTML = `
    <div class="course-main-info">
      <div class="course-title-row">
        <h3 class="course-name">${escapeHtml(courseLabel(course))}</h3>
        <span class="badge badge-credit">${course.credits ?? 3.0} 学分</span>
        <span class="badge badge-category">${escapeHtml(categoryText)}</span>
        <span class="badge badge-gpa">所剩最高均绩: ${maxGpaText}</span>
        <span class="badge badge-classes">合格教学班: ${course.qualified_classes_count} / ${course.total_classes_count} 个</span>
      </div>
      <p class="course-meta">共收录 ${course.total_classes_count} 个教学班，经课表时间与样本量筛选后保留 ${course.qualified_classes_count} 个合格班级</p>
    </div>
  `;
  article.appendChild(summary);

  // 渲染合格教学班列表
  const classesArea = document.createElement('div');
  classesArea.className = 'classes-area';

  let rowsHtml = '';
  const classes = course.classes || [];
  classes.forEach((cls) => {
    const gpaDisplay = cls.average !== null ? Number(cls.average).toFixed(2) : '—';
    const stdDisplay = cls.std_gpa !== null ? Number(cls.std_gpa).toFixed(2) : '—';
    const ratingDisplay = cls.rating !== null ? Number(cls.rating).toFixed(1) : '—';
    const samplesDisplay = cls.total_count ? `${cls.total_count} 人` : '—';

    rowsHtml += `
      <tr>
        <td class="class-id">${escapeHtml(cls.class_id)}</td>
        <td class="teacher-name">${escapeHtml(cls.teacher)} ${cls.college ? `<span class="hint">(${escapeHtml(cls.college)})</span>` : ''}</td>
        <td class="gpa-val">${gpaDisplay}</td>
        <td>${stdDisplay}</td>
        <td>${escapeHtml(samplesDisplay)}</td>
        <td>${ratingDisplay}</td>
        <td><span class="schedule-pill" title="该教学班列出的所有上课时段均已完整嵌入所选课表">🕒 ${escapeHtml(cls.schedule)} <span class="badge-embedded">全嵌入</span></span></td>
      </tr>
    `;
  });

  const conflictCount = course.total_classes_count - course.qualified_classes_count;
  const conflictNoteHtml = conflictCount > 0
    ? `<div class="conflict-classes-note">⚠️ 另有 ${conflictCount} 个教学班因部分或全部排课时间不在所选时段内，或样本量低于阈值未被纳入。</div>`
    : '';

  classesArea.innerHTML = `
    <div class="classes-header">
      <span class="classes-title">合格教学班均绩列表（按均绩降序排列）</span>
      <span class="classes-desc">列出的全部排课时间均已严格嵌入所选课表时段</span>
    </div>
    <div style="overflow-x: auto;">
      <table class="classes-table">
        <thead>
          <tr>
            <th>班级编号</th>
            <th>任课教师</th>
            <th>平均 GPA</th>
            <th>标准差</th>
            <th>样本人数</th>
            <th>查老师评分</th>
            <th>排课时间（所列全部时间均已嵌入）</th>
          </tr>
        </thead>
        <tbody>${rowsHtml}</tbody>
      </table>
    </div>
    ${conflictNoteHtml}
  `;

  article.appendChild(classesArea);
  return article;
}

// ====================== 既有搜索与批量排名增强（显示学分） ======================
function addCourseCard(target, course, withButton = true) {
  const fragment = document.querySelector('#course-template').content.cloneNode(true);
  const card = fragment.querySelector('.course-result');
  card.querySelector('.course-name').textContent = courseLabel(course);

  // 展示学分与分类
  const creditBadge = card.querySelector('.badge-credit');
  if (creditBadge) {
    creditBadge.textContent = `${course.credits ?? 3.0} 学分`;
  }
  const categoryBadge = card.querySelector('.badge-category');
  if (categoryBadge) {
    if (course.category_l1) {
      categoryBadge.textContent = `${course.category_l1} · ${course.category_l2}`;
    } else {
      categoryBadge.remove();
    }
  }

  card.querySelector('.course-meta').textContent = course.teachers?.length
    ? `静态数据收录 ${course.teachers.length} 位任课老师${course.max_gpa ? ` · 最高均绩 ${course.max_gpa.toFixed(2)}` : ''}`
    : '未收录任课老师';

  const button = card.querySelector('.rank-button');
  if (!withButton) button.remove();
  else button.addEventListener('click', () => loadRanking(course, card, button));

  target.appendChild(fragment);
  return target.lastElementChild;
}

function renderRanking(card, result) {
  const area = card.querySelector('.ranking-area');
  area.hidden = false;
  const rows = result.rankings || [];
  const warning = (result.warnings || []).slice(0, 5).map(escapeHtml).join('<br>');
  let body = rows.map(row => `
    <tr>
      <td>${row.rank}</td>
      <td>${escapeHtml(row.teacher)}</td>
      <td class="num">${row.average !== null ? Number(row.average).toFixed(2) : '暂无'}</td>
      <td>${row.std_gpa !== null ? Number(row.std_gpa).toFixed(2) : '—'}</td>
      <td>${escapeHtml(row.total_count || '—')}</td>
      <td>${row.rating !== null ? Number(row.rating).toFixed(1) : '—'}</td>
    </tr>
  `).join('');
  if (!body) body = '<tr><td colspan="6">没有可用的均绩记录。</td></tr>';

  area.innerHTML = `
    <div class="ranking-toolbar">
      <strong>任课老师均绩排行</strong>
      <p>学分: ${result.credits ?? 3.0} 学分 · 按平均 GPA 从高到低</p>
    </div>
    <table>
      <thead>
        <tr>
          <th>排名</th>
          <th>老师</th>
          <th>平均 GPA</th>
          <th>标准差</th>
          <th>样本人数</th>
          <th>查老师评分</th>
        </tr>
      </thead>
      <tbody>${body}</tbody>
    </table>
    ${warning ? `<p class="warning">${warning}</p>` : ''}
  `;
}

async function loadRanking(course, card, button) {
  button.disabled = true;
  button.textContent = '查询中...';
  try {
    const data = await request('/api/rank', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ course })
    });
    renderRanking(card, data.course);
    button.textContent = '重新查询';
  } catch (error) {
    const area = card.querySelector('.ranking-area');
    area.hidden = false;
    area.innerHTML = `<p class="error">${escapeHtml(error.message)}</p>`;
    button.textContent = '重试';
  } finally {
    button.disabled = false;
  }
}

searchForm.addEventListener('submit', async event => {
  event.preventDefault();
  const query = searchInput.value.trim();
  searchResults.hidden = false;
  searchResults.innerHTML = '<p class="status-text">正在检索本地课程数据...</p>';
  try {
    const data = await request(`/api/search?q=${encodeURIComponent(query)}`);
    searchResults.innerHTML = `<h2 class="result-heading">匹配课程</h2>`;
    if (!data.courses.length) searchResults.innerHTML += '<p class="status-text">没有匹配课程。</p>';
    data.courses.forEach(course => addCourseCard(searchResults, course));
  } catch (error) {
    renderError(searchResults, error.message);
  }
});

function readPlanCourses() {
  return [...new Set(planInput.value.split(/\r?\n/).map(name => name.trim()).filter(Boolean))].slice(0, 80);
}

function updatePlanStatus() {
  const courses = readPlanCourses();
  batchButton.disabled = !courses.length;
  batchStatus.textContent = courses.length ? `已输入 ${courses.length} 门课程。` : '';
}

planInput.addEventListener('input', updatePlanStatus);

batchButton.addEventListener('click', async () => {
  const courses = readPlanCourses();
  if (!courses.length) return;
  batchButton.disabled = true;
  batchResults.hidden = false;
  batchResults.innerHTML = '<p class="status-text">正在匹配本地均绩数据...</p>';
  try {
    const data = await request('/api/batch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ courses })
    });
    batchResults.innerHTML = '<h2 class="result-heading">培养方案课程排行</h2>';
    data.courses.forEach(course => {
      const card = addCourseCard(batchResults, course, false);
      renderRanking(card, course);
    });
  } catch (error) {
    renderError(batchResults, error.message);
  } finally {
    updatePlanStatus();
  }
});

// ====================== 页面初始化 ======================
document.addEventListener('DOMContentLoaded', () => {
  renderTimetableGrid();
  loadCategories();
  fetchFilteredCourses(1);
});

