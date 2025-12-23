/**
 * Recipe: x_extract_tweet_with_comments
 * Platform: x.com (Twitter)
 * Description: Extract tweet content, statistics, and comment list (up to 40 comments)
 * Created: 2025-11-19
 * Version: 1
 */

(async function() {
  // Helper function: wait
  const wait = (ms) => new Promise(resolve => setTimeout(resolve, ms));

  // Helper function: parse information from article's innerText
  function parseArticleText(text) {
    const lines = text.split('\n').map(l => l.trim()).filter(l => l);

    // Find author name and username (usually in the first few lines)
    let author = '';
    let username = '';
    for (let i = 0; i < Math.min(5, lines.length); i++) {
      if (lines[i].startsWith('@')) {
        username = lines[i];
        author = lines[i - 1] || '';
        break;
      }
    }

    // Extract tweet content (skip author info and timestamp, extract middle part)
    let contentLines = [];
    let contentStarted = false;
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      // Skip author, username, timestamp
      if (line === author || line === username || line.includes('·') || line.match(/^\d+[hms]$/)) {
        continue;
      }
      // Skip statistics (Views, pure numbers, K/M suffix)
      if (line === 'Views' || line.match(/^[\d.]+[KM]?$/)) {
        break;
      }
      // Content section
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

  // Helper function: extract statistics from innerText
  function parseStats(text) {
    const lines = text.split('\n').map(l => l.trim());
    const numbers = lines.filter(l => l.match(/^[\d.]+[KM]?$/));

    // Tweet statistics usually in order: replies, retweets, likes, bookmarks, views
    // Comment statistics usually only have: views
    return {
      replies: numbers[0] || '0',
      retweets: numbers[1] || '0',
      likes: numbers[2] || '0',
      bookmarks: numbers[3] || '0',
      views: numbers[4] || numbers[0] || '0'
    };
  }

  // Step 1: Extract main tweet information
  const articles = document.querySelectorAll('article');
  if (articles.length === 0) {
    throw new Error('Tweet article element not found, please ensure you have navigated to the tweet page');
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

  // Step 2: Scroll and load comments until 40 (or no more comments)
  const targetComments = 40;
  let previousCount = articles.length;
  let noNewCommentsCount = 0;
  let scrollCount = 0;
  const maxScrolls = 15; // Maximum 15 scrolls to avoid timeout

  while (scrollCount < maxScrolls) {
    const currentArticles = document.querySelectorAll('article');
    const currentCommentCount = currentArticles.length - 1; // Subtract main tweet

    // Target count reached
    if (currentCommentCount >= targetComments) {
      break;
    }

    // Scroll to load more
    window.scrollBy(0, 1000);
    await wait(800); // Reduced wait time to 800ms
    scrollCount++;

    // Check if new comments loaded
    const newArticles = document.querySelectorAll('article');
    if (newArticles.length === previousCount) {
      noNewCommentsCount++;
      // 2 consecutive times with no new comments means reached bottom (reduced to 2)
      if (noNewCommentsCount >= 2) {
        break;
      }
    } else {
      noNewCommentsCount = 0;
      previousCount = newArticles.length;
    }
  }

  // Step 3: Extract comment list (skip first article, which is the main tweet)
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

  // Return structured data
  return {
    tweet: mainTweet,
    comments: comments,
    meta: {
      totalCommentsExtracted: comments.length,
      targetComments: targetComments
    }
  };
})();
