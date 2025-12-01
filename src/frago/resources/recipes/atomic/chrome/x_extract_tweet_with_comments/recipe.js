/**
 * Recipe: x_extract_tweet_with_comments
 * Platform: x.com (Twitter)
 * Description: 提取推文内容、统计数据及评论列表（最多40条）
 * Created: 2025-11-19
 * Version: 1
 */

(async function() {
  // 辅助函数：等待
  const wait = (ms) => new Promise(resolve => setTimeout(resolve, ms));

  // 辅助函数：从article的innerText中解析信息
  function parseArticleText(text) {
    const lines = text.split('\n').map(l => l.trim()).filter(l => l);

    // 查找作者名和用户名（通常在前几行）
    let author = '';
    let username = '';
    for (let i = 0; i < Math.min(5, lines.length); i++) {
      if (lines[i].startsWith('@')) {
        username = lines[i];
        author = lines[i - 1] || '';
        break;
      }
    }

    // 提取推文内容（跳过作者信息和时间戳，提取中间部分）
    let contentLines = [];
    let contentStarted = false;
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      // 跳过作者、用户名、时间戳
      if (line === author || line === username || line.includes('·') || line.match(/^\d+[hms]$/)) {
        continue;
      }
      // 跳过统计数据（Views, 纯数字，K/M后缀）
      if (line === 'Views' || line.match(/^[\d.]+[KM]?$/)) {
        break;
      }
      // 内容部分
      if (!contentStarted && line.length > 0) {
        contentStarted = true;
      }
      if (contentStarted) {
        contentLines.push(line);
      }
    }

    return {
      author: author,
      username: username,
      content: contentLines.join('\n').trim()
    };
  }

  // 辅助函数：从innerText中提取统计数据
  function parseStats(text) {
    const lines = text.split('\n').map(l => l.trim());
    const numbers = lines.filter(l => l.match(/^[\d.]+[KM]?$/));

    // 推文统计数据通常顺序为：评论数、转发数、点赞数、书签数、浏览数
    // 评论统计数据通常只有：浏览数
    return {
      replies: numbers[0] || '0',
      retweets: numbers[1] || '0',
      likes: numbers[2] || '0',
      bookmarks: numbers[3] || '0',
      views: numbers[4] || numbers[0] || '0'
    };
  }

  // 步骤1：提取主推文信息
  const articles = document.querySelectorAll('article');
  if (articles.length === 0) {
    throw new Error('未找到推文article元素，请确保已导航到推文页面');
  }

  const mainTweetArticle = articles[0];
  const mainTweetText = mainTweetArticle.innerText;
  const mainTweetParsed = parseArticleText(mainTweetText);
  const mainTweetStats = parseStats(mainTweetText);

  const mainTweet = {
    author: mainTweetParsed.author,
    username: mainTweetParsed.username,
    content: mainTweetParsed.content,
    stats: mainTweetStats
  };

  // 步骤2：滚动加载评论直到40条（或无更多评论）
  const targetComments = 40;
  let previousCount = articles.length;
  let noNewCommentsCount = 0;
  let scrollCount = 0;
  const maxScrolls = 15; // 最多滚动15次，避免超时

  while (scrollCount < maxScrolls) {
    const currentArticles = document.querySelectorAll('article');
    const currentCommentCount = currentArticles.length - 1; // 减去主推文

    // 已达到目标数量
    if (currentCommentCount >= targetComments) {
      break;
    }

    // 滚动加载更多
    window.scrollBy(0, 1000);
    await wait(800); // 减少等待时间到800ms
    scrollCount++;

    // 检查是否有新评论加载
    const newArticles = document.querySelectorAll('article');
    if (newArticles.length === previousCount) {
      noNewCommentsCount++;
      // 连续2次没有新评论，说明已到底部（减少到2次）
      if (noNewCommentsCount >= 2) {
        break;
      }
    } else {
      noNewCommentsCount = 0;
      previousCount = newArticles.length;
    }
  }

  // 步骤3：提取评论列表（跳过第一个article，它是主推文）
  const allArticles = document.querySelectorAll('article');
  const comments = [];

  for (let i = 1; i < Math.min(allArticles.length, targetComments + 1); i++) {
    const commentArticle = allArticles[i];
    const commentText = commentArticle.innerText;
    const commentParsed = parseArticleText(commentText);
    const commentStats = parseStats(commentText);

    comments.push({
      author: commentParsed.author,
      username: commentParsed.username,
      content: commentParsed.content,
      stats: {
        views: commentStats.views
      }
    });
  }

  // 返回结构化数据
  return {
    tweet: mainTweet,
    comments: comments,
    meta: {
      totalCommentsExtracted: comments.length,
      targetComments: targetComments
    }
  };
})();
