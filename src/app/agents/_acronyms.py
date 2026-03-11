"""Microsoft acronym database and decoder tool."""

from agent_framework._tools import ai_function


# Microsoft acronym database for the decoder tool
MICROSOFT_ACRONYMS = {
    # Azure & Cloud
    "ARM": ("Azure Resource Manager", "The deployment and management service for Azure that provides a management layer to create, update, and delete resources."),
    "AKS": ("Azure Kubernetes Service", "Managed Kubernetes container orchestration service in Azure."),
    "ACA": ("Azure Container Apps", "Serverless container platform for running microservices and containerized apps."),
    "ACR": ("Azure Container Registry", "Private Docker registry service for storing and managing container images."),
    "AAD": ("Azure Active Directory", "Cloud-based identity and access management service (now Microsoft Entra ID)."),
    "ASE": ("App Service Environment", "Fully isolated, dedicated environment for running App Service apps at high scale."),
    "AVD": ("Azure Virtual Desktop", "Desktop and app virtualization service running in the cloud."),
    "APIM": ("API Management", "Hybrid, multi-cloud management platform for APIs across all environments."),
    "RBAC": ("Role-Based Access Control", "Authorization system for managing access to Azure resources."),
    "SAS": ("Shared Access Signature", "URI that grants restricted access rights to Azure Storage resources."),
    "SKU": ("Stock Keeping Unit", "Defines the pricing tier and capabilities of Azure resources."),
    "VNET": ("Virtual Network", "Fundamental building block for private networks in Azure."),
    "NSG": ("Network Security Group", "Contains security rules that allow or deny network traffic."),
    "PaaS": ("Platform as a Service", "Cloud computing model where provider delivers hardware and software tools."),
    "IaaS": ("Infrastructure as a Service", "Cloud computing model providing virtualized computing resources."),
    "SaaS": ("Software as a Service", "Software licensing model where applications are accessed over the internet."),

    # Microsoft 365 & Productivity
    "M365": ("Microsoft 365", "Subscription service including Office apps, cloud services, and security."),
    "O365": ("Office 365", "Legacy name for cloud-based productivity suite (now part of Microsoft 365)."),
    "SPO": ("SharePoint Online", "Cloud-based collaboration and document management platform."),
    "EXO": ("Exchange Online", "Cloud-based email and calendaring service."),
    "ODfB": ("OneDrive for Business", "Enterprise file hosting and synchronization service."),
    "Teams": ("Microsoft Teams", "Collaboration platform combining chat, video, file storage, and app integration."),
    "PAM": ("Privileged Access Management", "Security solution for managing elevated access permissions."),
    "DLP": ("Data Loss Prevention", "Set of tools and processes to prevent data breaches and exfiltration."),

    # Development & DevOps
    "ADO": ("Azure DevOps", "Set of development tools for software teams including repos, pipelines, boards."),
    "CLI": ("Command Line Interface", "Text-based interface for interacting with software and operating systems."),
    "SDK": ("Software Development Kit", "Collection of tools for developing applications for specific platforms."),
    "API": ("Application Programming Interface", "Set of protocols for building and integrating application software."),
    "REST": ("Representational State Transfer", "Architectural style for designing networked applications."),
    "CI/CD": ("Continuous Integration/Continuous Deployment", "Practice of automating integration and deployment of code changes."),
    "IaC": ("Infrastructure as Code", "Managing infrastructure through code rather than manual processes."),
    "VS": ("Visual Studio", "Full-featured IDE for developing applications on Windows, web, cloud."),
    "VSC": ("Visual Studio Code", "Lightweight, cross-platform source code editor."),

    # AI & Data
    "AOAI": ("Azure OpenAI", "Azure service providing access to OpenAI's models including GPT-4."),
    "AML": ("Azure Machine Learning", "Cloud service for training, deploying, and managing ML models."),
    "ADF": ("Azure Data Factory", "Cloud-based data integration service for creating data-driven workflows."),
    "ADB": ("Azure Databricks", "Apache Spark-based analytics platform optimized for Azure."),
    "RAG": ("Retrieval-Augmented Generation", "AI technique combining retrieval with generation for grounded responses."),
    "LLM": ("Large Language Model", "AI model trained on vast text data for language understanding and generation."),
    "GPT": ("Generative Pre-trained Transformer", "Type of large language model architecture from OpenAI."),
    "NLP": ("Natural Language Processing", "AI field focused on interaction between computers and human language."),

    # Security & Identity
    "MFA": ("Multi-Factor Authentication", "Security process requiring multiple forms of verification."),
    "SSO": ("Single Sign-On", "Authentication scheme allowing access to multiple applications with one login."),
    "MSAL": ("Microsoft Authentication Library", "Library for authenticating users and acquiring tokens."),
    "SPN": ("Service Principal Name", "Identity used by services or applications to access Azure resources."),
    "UAMI": ("User-Assigned Managed Identity", "Azure identity that can be assigned to multiple resources."),
    "SAMI": ("System-Assigned Managed Identity", "Identity tied to a specific Azure resource's lifecycle."),
    "PIM": ("Privileged Identity Management", "Service for managing, controlling, and monitoring privileged access."),
    "CAP": ("Conditional Access Policy", "Policies that control access based on conditions like location or device."),

    # Copilot & AI Assistants
    "M365C": ("Microsoft 365 Copilot", "AI assistant integrated into Microsoft 365 apps."),
    "GHC": ("GitHub Copilot", "AI pair programmer that suggests code in your editor."),
    "MAF": ("Microsoft Agent Framework", "SDK for building AI agents with tools and multi-agent support."),
    "MCP": ("Model Context Protocol", "Protocol for providing context to AI models from external sources."),
}


@ai_function
def decode_microsoft_acronym(acronym: str) -> str:
    """
    Decode a Microsoft/Azure/tech acronym and explain what it means.

    Use this tool when users ask about Microsoft acronyms, abbreviations,
    or technical terms they don't understand.

    Args:
        acronym: The acronym to decode (e.g., "AKS", "RBAC", "M365")

    Returns:
        The full name and explanation of the acronym
    """
    # Normalize input
    acronym_upper = acronym.upper().strip()

    if acronym_upper in MICROSOFT_ACRONYMS:
        full_name, description = MICROSOFT_ACRONYMS[acronym_upper]
        return f"**{acronym_upper}** = {full_name}\n\n{description}"

    # Try partial match
    partial_matches = [
        (key, val) for key, val in MICROSOFT_ACRONYMS.items()
        if acronym_upper in key or key in acronym_upper
    ]

    if partial_matches:
        results = [f"**{key}** = {val[0]}: {val[1]}" for key, val in partial_matches[:3]]
        return f"No exact match for '{acronym}'. Did you mean:\n\n" + "\n\n".join(results)

    return f"I don't have '{acronym}' in my acronym database. Try using web search to find its meaning, or it might not be a standard Microsoft term."
