/**
 * Recipe: upwork_extract_job_details_as_markdown
 * Platform: upwork
 * Description: 从Upwork job详情页提取完整信息并格式化为Markdown
 * Created: 2025-11-20
 * Version: 1
 */

(async function() {
  // 辅助函数：按优先级尝试多个选择器
  function findElement(selectors, description) {
    for (const sel of selectors) {
      const elem = document.querySelector(sel.selector);
      if (elem) return elem;
    }
    throw new Error(`无法找到${description}：${selectors.map(s => s.selector).join(', ')}`);
  }

  // 1. 提取Job标题
  const titleElem = findElement([
    { selector: 'h2', priority: 3 },
    { selector: 'h3', priority: 3 },
    { selector: 'h4', priority: 3 }
  ], 'Job标题');
  const title = titleElem.innerText.trim();

  // 2. 提取发布时间和地点（通过main的innerText解析）
  const mainText = document.querySelector('main').innerText;
  const postedMatch = mainText.match(/Posted\s+(.+?)\n/);
  const postedTime = postedMatch ? postedMatch[1] : 'Unknown';

  // 地点通常在标题后的几行内
  const locationMatch = mainText.match(/Posted.*?\n\n(.+?)\n/s);
  const location = locationMatch ? locationMatch[1].trim() : 'Not specified';

  // 3. 提取完整Job描述
  const descElem = findElement([
    { selector: '[data-test="Description"]', priority: 5 }
  ], 'Job描述');
  const description = descElem.innerText.trim();

  // 4. 提取技能列表
  const skillsSection = Array.from(document.querySelectorAll('section')).find(s =>
    s.textContent.includes('Skills and Expertise')
  );
  let skills = [];
  if (skillsSection) {
    const skillElements = skillsSection.querySelectorAll('span[class*="skill"], button[class*="skill"]');
    skills = Array.from(skillElements).map(s => s.innerText.trim()).filter(s => s.length > 0 && s !== 'Skills and Expertise');

    // 如果上面的方法没找到，尝试直接提取文本并解析
    if (skills.length === 0) {
      const skillsText = skillsSection.innerText;
      const lines = skillsText.split('\n').filter(line =>
        line.trim() &&
        line !== 'Skills and Expertise' &&
        line !== 'Mandatory skills' &&
        !line.includes('See more')
      );
      skills = lines;
    }
  }

  // 5. 提取元数据（预算、提案、项目类型等）
  const metaList = document.querySelectorAll('main ul li');
  const metaItems = Array.from(metaList).map(li => li.innerText.trim());

  // 解析元数据
  let budget = 'N/A';
  let budgetType = 'N/A';
  let proposals = 'N/A';
  let projectType = 'N/A';
  let duration = 'N/A';
  let workload = 'N/A';
  let experienceLevel = 'N/A';

  metaItems.forEach(item => {
    if (item.includes('$') && item.includes('Hourly')) {
      const match = item.match(/\$[\d,.]+/);
      budget = match ? match[0] : 'N/A';
      budgetType = 'Hourly';
    } else if (item.includes('$') && item.includes('Fixed')) {
      const match = item.match(/\$[\d,.]+/);
      budget = match ? match[0] : 'N/A';
      budgetType = 'Fixed Price';
    } else if (item.includes('Proposals:')) {
      proposals = item.replace('Proposals:', '').trim();
    } else if (item.includes('Project Type:')) {
      projectType = item.replace('Project Type:', '').trim();
    } else if (item.includes('Duration') && (item.includes('month') || item.includes('week'))) {
      duration = item.replace('Duration', '').trim();
    } else if (item.includes('hrs/week')) {
      workload = item.replace('Hourly', '').trim();
    } else if ((item.includes('Intermediate') || item.includes('Expert') || item.includes('Entry')) &&
               experienceLevel === 'N/A') {
      // 只提取第一个匹配的经验级别，且长度要合理
      const lines = item.split('\n');
      for (const line of lines) {
        if ((line.includes('Intermediate') || line.includes('Expert') || line.includes('Entry')) &&
            line.length < 50 && !line.includes('$')) {
          experienceLevel = line.trim();
          break;
        }
      }
    }
  });

  // 6. 提取客户信息
  const clientElem = findElement([
    { selector: '[data-test="about-client-container"]', priority: 5 }
  ], '客户信息');
  const clientText = clientElem.innerText;

  // 解析客户信息
  const ratingMatch = clientText.match(/Rating is ([\d.]+)|^([\d.]+)$/m);
  const clientRating = ratingMatch ? (ratingMatch[1] || ratingMatch[2]) : 'N/A';

  const reviewsMatch = clientText.match(/([\d.]+)\s+of\s+(\d+)\s+reviews/);
  const clientReviews = reviewsMatch ? reviewsMatch[2] : 'N/A';

  // 提取客户地点（国家和城市，在时间戳前面）
  const locationClientMatch = clientText.match(/(United States|Canada|United Kingdom|[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\n([A-Za-z\s]+)\d{1,2}:\d{2}\s+[AP]M/);
  const clientLocation = locationClientMatch ? `${locationClientMatch[1]}, ${locationClientMatch[2].trim()}` :
                          clientText.match(/United States|Canada|United Kingdom/) ? clientText.match(/United States|Canada|United Kingdom/)[0] : 'N/A';

  const jobsPostedMatch = clientText.match(/(\d+)\s+jobs posted/);
  const clientJobsPosted = jobsPostedMatch ? jobsPostedMatch[1] : 'N/A';

  const hireRateMatch = clientText.match(/(\d+)%\s+hire rate/);
  const clientHireRate = hireRateMatch ? hireRateMatch[1] + '%' : 'N/A';

  const totalSpentMatch = clientText.match(/\$([\d.]+[KMB]?)\s+total spent/);
  const clientTotalSpent = totalSpentMatch ? '$' + totalSpentMatch[1] : 'N/A';

  const hiresMatch = clientText.match(/(\d+)\s+hires/);
  const clientTotalHires = hiresMatch ? hiresMatch[1] : 'N/A';

  const avgRateMatch = clientText.match(/\$([\d.]+)\s+\/hr\s+avg/);
  const clientAvgRate = avgRateMatch ? '$' + avgRateMatch[1] + '/hr' : 'N/A';

  const memberSinceMatch = clientText.match(/Member since\s+(.+?)$/m);
  const clientMemberSince = memberSinceMatch ? memberSinceMatch[1].trim() : 'N/A';

  // 7. 生成Markdown格式输出
  const markdown = `# ${title}

## Job元数据

| 字段 | 值 |
|------|-----|
| **发布时间** | ${postedTime} |
| **地点** | ${location} |
| **项目类型** | ${projectType} |
| **预算方式** | ${budgetType} |
| **预算** | ${budget} |
| **工作量** | ${workload} |
| **项目时长** | ${duration} |
| **经验级别** | ${experienceLevel} |
| **提案数量** | ${proposals} |

## Job描述

${description}

## 技能要求

${skills.length > 0 ? skills.map(s => `- ${s}`).join('\n') : 'N/A'}

## 客户信息

| 字段 | 值 |
|------|-----|
| **评分** | ${clientRating} (${clientReviews} reviews) |
| **地点** | ${clientLocation} |
| **发布工作数** | ${clientJobsPosted} |
| **雇佣率** | ${clientHireRate} |
| **总支出** | ${clientTotalSpent} |
| **总雇佣次数** | ${clientTotalHires} |
| **平均时薪** | ${clientAvgRate} |
| **成员时间** | ${clientMemberSince} |
`;

  return markdown;
})();
