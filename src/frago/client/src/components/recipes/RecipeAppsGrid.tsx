/**
 * RecipeAppsGrid — Grid layout of recipe "app cards".
 *
 * Design: 4-column grid, each recipe as an app card with icon, title,
 * description, status, and run button. Plus a "+" card at the end.
 */

import { useEffect, useState, useMemo } from 'react';
import { useAppStore } from '@/stores/appStore';
import { Search, X, Plus } from 'lucide-react';
import RecipeAppCard from './RecipeAppCard';
import RecipeRunModal from './RecipeRunModal';
import type { RecipeItem } from '@/types/pywebview';

export default function RecipeAppsGrid() {
  const { recipes, loadRecipes, skills, loadSkills, switchPage } = useAppStore();
  const [search, setSearch] = useState('');
  const [activeTab, setActiveTab] = useState<'recipes' | 'skills'>('recipes');
  const [runModalRecipe, setRunModalRecipe] = useState<string | null>(null);

  useEffect(() => {
    loadRecipes();
    loadSkills();
  }, [loadRecipes, loadSkills]);

  const filteredRecipes = useMemo(() => {
    if (!search.trim()) return recipes;
    const query = search.toLowerCase();
    return recipes.filter(
      (r) =>
        r.name.toLowerCase().includes(query) ||
        (r.description || '').toLowerCase().includes(query) ||
        r.tags.some((t) => t.toLowerCase().includes(query))
    );
  }, [recipes, search]);

  const handleRunClick = (recipe: RecipeItem) => {
    setRunModalRecipe(recipe.name);
  };

  const handleCardClick = (recipe: RecipeItem) => {
    switchPage('recipe_detail', recipe.name);
  };

  return (
    <div className="recipe-grid-page">
      {/* Header: Tabs + Search */}
      <div className="recipe-grid-header">
        <div className="recipe-grid-tabs">
          <button
            className={`recipe-grid-tab ${activeTab === 'recipes' ? 'recipe-grid-tab--active' : ''}`}
            onClick={() => setActiveTab('recipes')}
          >
            recipes
          </button>
          <button
            className={`recipe-grid-tab ${activeTab === 'skills' ? 'recipe-grid-tab--active' : ''}`}
            onClick={() => setActiveTab('skills')}
          >
            skills
          </button>
        </div>
        <div className="recipe-grid-search">
          <Search size={14} className="recipe-grid-search-icon" />
          <input
            type="text"
            placeholder="搜索配方 ..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="recipe-grid-search-input"
          />
          {search && (
            <button className="recipe-grid-search-clear" onClick={() => setSearch('')}>
              <X size={12} />
            </button>
          )}
        </div>
      </div>

      {/* Grid */}
      {activeTab === 'recipes' ? (
        <div className="recipe-grid">
          {filteredRecipes.map((recipe) => (
            <RecipeAppCard
              key={recipe.name}
              recipe={recipe}
              onRun={() => handleRunClick(recipe)}
              onClick={() => handleCardClick(recipe)}
            />
          ))}
          {/* Add recipe card */}
          <div className="recipe-card recipe-card--add">
            <div className="recipe-card-add-icon">
              <Plus size={24} />
            </div>
            <span className="recipe-card-add-text">添加配方</span>
          </div>
        </div>
      ) : (
        <div className="recipe-grid">
          {skills.map((skill) => (
            <div key={skill.name} className="recipe-card">
              <div className="recipe-card-header">
                <div className="recipe-card-icon">
                  <span>{skill.name.charAt(0).toUpperCase()}</span>
                </div>
              </div>
              <div className="recipe-card-body">
                <h3 className="recipe-card-title">{skill.name}</h3>
                <p className="recipe-card-desc">{skill.description || ''}</p>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Run Modal */}
      {runModalRecipe && (
        <RecipeRunModal
          recipeName={runModalRecipe}
          onClose={() => setRunModalRecipe(null)}
        />
      )}
    </div>
  );
}
