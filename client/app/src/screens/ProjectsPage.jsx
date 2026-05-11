import { useState } from "react";
import Header from "../components/common/Header";
import ProjectPicker from "../components/common/ProjectPicker";
import ShareProjectDialog from "../components/common/ShareProjectDialog";

export default function ProjectsPage({
  projects,
  onOpenProject,
  onOpenUserMemory,
  getToken,
  currentUserOid,
}) {
  const [sharingProject, setSharingProject] = useState(null);

  return (
    <div className="h-screen flex flex-col bg-[#f3f2f1]">
      <Header onOpenUserMemory={onOpenUserMemory} />
      <ProjectPicker
        projects={projects.projects}
        loading={projects.loading}
        error={projects.error}
        onOpen={onOpenProject}
        onCreate={(name, description) => projects.create(name, description)}
        onDelete={(id) => projects.remove(id)}
        onRename={(id, name) => projects.rename(id, name)}
        onShare={(p) => setSharingProject(p)}
      />
      <ShareProjectDialog
        open={!!sharingProject}
        onClose={() => setSharingProject(null)}
        projectId={sharingProject?.id}
        projectName={sharingProject?.name}
        callerRole={sharingProject?.role}
        currentUserOid={currentUserOid}
        getToken={getToken}
        onLeftProject={() => {
          setSharingProject(null);
          projects.refresh?.();
        }}
      />
    </div>
  );
}
