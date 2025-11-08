# Design Specifications - Social Media Python Publisher

**Document Version:** 2.0  
**Last Updated:** November 7, 2025  
**Status:** Active Development

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Architecture Design](#2-architecture-design)
3. [Component Specifications](#3-component-specifications)
4. [Data Models](#4-data-models)
5. [API Specifications](#5-api-specifications)
6. [Database Design](#6-database-design)
7. [Security Architecture](#7-security-architecture)
8. [Deployment Architecture](#8-deployment-architecture)
9. [Integration Patterns](#9-integration-patterns)
10. [Future Enhancements](#10-future-enhancements)

---

## 1. System Overview

### 1.1 Purpose

The Social Media Python Publisher is an intelligent automation system designed to streamline content distribution across multiple social media platforms. It combines cloud storage, artificial intelligence, and social media APIs to create a seamless, automated workflow for posting visual content with AI-generated captions.

### 1.2 System Goals

- **Automation**: Eliminate manual content posting across multiple platforms
- **Intelligence**: Leverage AI to generate contextually relevant captions
- **Reliability**: Ensure consistent posting with error recovery
- **Scalability**: Support multiple platforms and content types
- **Maintainability**: Clean architecture for easy extension and maintenance
- **Security**: Protect user credentials and sensitive data

### 1.3 Target Users

- **Primary**: Individual content creators and photographers
- **Secondary**: Small business social media managers
- **Tertiary**: Digital marketing agencies

### 1.4 System Constraints

- **Technical**: Python 3.12 environment required (3.11+ supported)
- **Financial**: Dependent on external API pricing (OpenAI, Replicate)
- **Legal**: Instagram integration uses unofficial API (TOS compliance risk)
- **Performance**: Sequential workflow for single-image processing

### 1.5 Success Metrics

- **Reliability**: 99%+ successful post rate
- **Performance**: < 30 seconds end-to-end execution time
- **Availability**: 24/7 operation capability
- **Cost**: < $5/month for 30 daily posts
- **Maintainability**: < 2 hours for adding new platform support

---

## 2. Architecture Design

### 2.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        User Interface Layer                      │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐   │
│  │   CLI Tool     │  │   Cron Jobs    │  │  Future: Web   │   │
│  └────────────────┘  └────────────────┘  └────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                       Application Layer                          │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                  Workflow Orchestrator                    │  │
│  │  (Main Business Logic - py_rotator_daily.py)             │  │
│  └──────────────────────────────────────────────────────────┘  │
│                              ↓                                   │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                    Service Layer                          │  │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐              │  │
│  │  │ Storage  │  │   AI     │  │Publishing│              │  │
│  │  │ Service  │  │ Service  │  │ Service  │              │  │
│  │  └──────────┘  └──────────┘  └──────────┘              │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                     Integration Layer                            │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │ Dropbox  │  │ OpenAI   │  │Replicate │  │  SMTP    │       │
│  │  Client  │  │  Client  │  │  Client  │  │  Client  │       │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘       │
│  ┌──────────┐  ┌──────────┐                                    │
│  │Instagram │  │ Telegram │                                    │
│  │  Client  │  │  Client  │                                    │
│  └──────────┘  └──────────┘                                    │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                      External Services                           │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │ Dropbox  │  │ OpenAI   │  │Replicate │  │Instagram │       │
│  │   API    │  │   API    │  │   API    │  │   API    │       │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘       │
│  ┌──────────┐  ┌──────────┐                                    │
│  │ Telegram │  │  Gmail   │                                    │
│  │   API    │  │   SMTP   │                                    │
│  └──────────┘  └──────────┘                                    │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 Architectural Patterns

#### 2.2.1 Current (V1): Procedural with Async Operations

**Pattern Type**: Procedural Programming with Async/Await

**Characteristics:**
- Functions as primary organizational unit
- Sequential workflow execution
- Async/await for I/O-bound operations
- Configuration-driven behavior

**Advantages:**
- Simple and straightforward
- Easy to understand for beginners
- Minimal boilerplate
- Fast initial development

**Disadvantages:**
- Limited extensibility
- Difficult to test in isolation
- Tight coupling between components
- No clear separation of concerns

#### 2.2.2 Recommended (V2): Layered Architecture with Dependency Injection

**Pattern Type**: Layered Architecture + Service Pattern + Dependency Injection

```
┌─────────────────────────────────────────────┐
│         Presentation Layer                   │
│  (CLI, Web UI, API Endpoints)               │
└─────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────┐
│         Application Layer                    │
│  (Workflow Orchestration, Use Cases)        │
└─────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────┐
│         Domain Layer                         │
│  (Business Logic, Domain Models)            │
└─────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────┐
│         Infrastructure Layer                 │
│  (External API Clients, File System, DB)    │
└─────────────────────────────────────────────┘
```

**Benefits:**
- Clear separation of concerns
- Testable components
- Easy to extend
- Maintainable codebase
- Support for dependency injection

---

### 2.3 Component Diagram (V2)

```
┌──────────────────────────────────────────────────────────────┐
│                     Main Application                          │
│                  (py_rotator_daily.py)                        │
│                                                               │
│  ┌────────────────────────────────────────────────────┐     │
│  │              Workflow Orchestrator                  │     │
│  │  - Coordinates all services                         │     │
│  │  - Manages execution flow                           │     │
│  │  - Handles errors and recovery                      │     │
│  └────────────────────────────────────────────────────┘     │
│                                                               │
│  ┌────────────────────────────────────────────────────┐     │
│  │           Configuration Manager                     │     │
│  │  - Reads INI files                                  │     │
│  │  - Loads environment variables                      │     │
│  │  - Validates configuration                          │     │
│  └────────────────────────────────────────────────────┘     │
└──────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────┐
│                       Service Components                      │
│                                                               │
│  ┌─────────────────┐  ┌─────────────────┐                   │
│  │ Storage Service │  │   AI Service    │                   │
│  │                 │  │                 │                   │
│  │ - List images   │  │ - Analyze image │                   │
│  │ - Download      │  │ - Generate      │                   │
│  │ - Archive       │  │   caption       │                   │
│  │ - Get links     │  │ - Replicate API │                   │
│  │                 │  │ - OpenAI API    │                   │
│  └─────────────────┘  └─────────────────┘                   │
│                                                               │
│  ┌──────────────────────────────────────────────────┐       │
│  │          Publishing Service                       │       │
│  │                                                   │       │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐      │       │
│  │  │Instagram │  │ Telegram │  │  Email   │      │       │
│  │  │Publisher │  │Publisher │  │Publisher │      │       │
│  │  └──────────┘  └──────────┘  └──────────┘      │       │
│  └──────────────────────────────────────────────────┘       │
│                                                               │
│  ┌─────────────────┐  ┌─────────────────┐                   │
│  │ Image Processor │  │  Logger Service │                   │
│  │                 │  │                 │                   │
│  │ - Resize        │  │ - Structured    │                   │
│  │ - Format        │  │   logging       │                   │
│  │ - Optimize      │  │ - Error         │                   │
│  │                 │  │   tracking      │                   │
│  └─────────────────┘  └─────────────────┘                   │
└──────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────┐
│                   Support Components                          │
│                                                               │
│  ┌─────────────────┐  ┌─────────────────┐                   │
│  │Error Handler    │  │  Retry Manager  │                   │
│  │                 │  │                 │                   │
│  │ - Custom        │  │ - Exponential   │                   │
│  │   exceptions    │  │   backoff       │                   │
│  │ - Recovery      │  │ - Rate limiting │                   │
│  └─────────────────┘  └─────────────────┘                   │
└──────────────────────────────────────────────────────────────┘
```

### 2.4 Data Flow Architecture (V2)

```
┌─────────────────────────────────────────────────────────────┐
│                    1. Initialization                         │
│                                                              │
│  Load Config (.env + .ini) → Validate → Create Clients     │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│                   2. Image Selection                         │
│                                                              │
│  List Dropbox Folder → Random Selection → Download Image    │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│                   3. AI Analysis                             │
│                                                              │
│  Generate Temp Link → Replicate (Caption + Mood)           │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│                4. Caption Generation                         │
│                                                              │
│  Combine Analysis → OpenAI GPT → Append Hashtags           │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│              5. Multi-Platform Distribution                  │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │  Instagram   │  │   Telegram   │  │    Email     │     │
│  │   (async)    │  │   (async)    │  │   (async)    │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
│        ↓                  ↓                  ↓              │
│    Success?           Success?          Success?            │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│                    6. Post-Processing                        │
│                                                              │
│  If Success → Archive Image in Dropbox                      │
│  Cleanup Temp Files → Log Results                           │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Component Specifications (V2)

### 3.1 Configuration Manager

**Responsibility:** Load, validate, and provide access to application configuration.

#### 3.1.1 Interface

```python
from typing import Dict, Any, Optional
from pathlib import Path

class ConfigurationManager:
    """Manages application configuration from multiple sources"""
    
    def __init__(self, config_file: Path, env_file: Optional[Path] = None):
        """Initialize configuration manager"""
        pass
    
    def load(self) -> Dict[str, Any]:
        """Load configuration from all sources"""
        pass
    
    def validate(self) -> bool:
        """Validate configuration completeness and correctness"""
        pass
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value by key"""
        pass
    
    def get_section(self, section: str) -> Dict[str, Any]:
        """Get entire configuration section"""
        pass
```

#### 3.1.2 Configuration Schema

```python
from pydantic import BaseModel, Field, validator

class DropboxConfig(BaseModel):
    app_key: str = Field(..., description="Dropbox application key")
    app_secret: str = Field(..., description="Dropbox application secret")
    refresh_token: str = Field(..., description="OAuth refresh token")
    image_folder: str = Field(..., description="Source image folder path")
    archive_folder: str = Field(default="archive", description="Archive folder name")
    
    @validator('image_folder')
    def validate_folder_path(cls, v):
        if not v.startswith('/'):
            raise ValueError('Folder path must start with /')
        return v

class OpenAIConfig(BaseModel):
    api_key: str = Field(..., description="OpenAI API key")
    engine: str = Field(default="gpt-3.5-turbo", description="Model to use")
    system_prompt: str = Field(..., description="System prompt for AI")
    role_prompt: str = Field(..., description="Role prompt prefix")
    
    @validator('api_key')
    def validate_api_key(cls, v):
        if not v.startswith('sk-'):
            raise ValueError('Invalid OpenAI API key format')
        return v

class ReplicateConfig(BaseModel):
    api_token: str = Field(..., description="Replicate API token")
    model: str = Field(..., description="Replicate model identifier")
    
    @validator('api_token')
    def validate_token(cls, v):
        if not v.startswith('r8_'):
            raise ValueError('Invalid Replicate token format')
        return v

class PlatformConfig(BaseModel):
    telegram_enabled: bool = False
    instagram_enabled: bool = False
    email_enabled: bool = False
    
class TelegramConfig(BaseModel):
    bot_token: str = Field(..., description="Telegram bot token")
    channel_id: str = Field(..., description="Channel or chat ID")

class InstagramConfig(BaseModel):
    username: str = Field(..., description="Instagram username")
    password: str = Field(..., description="Instagram password")
    session_file: str = Field(default="instasession.json")

class EmailConfig(BaseModel):
    sender: str = Field(..., description="Sender email address")
    recipient: str = Field(..., description="Recipient email address")
    password: str = Field(..., description="Email password")
    smtp_server: str = Field(default="smtp.gmail.com")
    smtp_port: int = Field(default=587)

class ContentConfig(BaseModel):
    hashtag_string: str = Field(default="", description="Hashtags to append")
    archive: bool = Field(default=True, description="Archive after posting")
    debug: bool = Field(default=False, description="Debug mode")

class ApplicationConfig(BaseModel):
    """Complete application configuration"""
    dropbox: DropboxConfig
    openai: OpenAIConfig
    replicate: ReplicateConfig
    platforms: PlatformConfig
    telegram: Optional[TelegramConfig]
    instagram: Optional[InstagramConfig]
    email: Optional[EmailConfig]
    content: ContentConfig
```

---

### 3.2 Storage Service

**Responsibility:** Handle all cloud storage operations with Dropbox.

#### 3.2.1 Interface

```python
from typing import List, Protocol
from pathlib import Path

class ImageStorage(Protocol):
    """Protocol for image storage operations"""
    
    async def list_images(self, folder: str) -> List[str]:
        """List all images in a folder"""
        ...
    
    async def download_image(self, folder: str, filename: str) -> bytes:
        """Download image as bytes"""
        ...
    
    async def get_temporary_link(self, folder: str, filename: str) -> str:
        """Get temporary shareable link"""
        ...
    
    async def archive_image(self, source_folder: str, filename: str, 
                          archive_folder: str) -> None:
        """Move image to archive folder"""
        ...

class DropboxStorage:
    """Dropbox implementation of ImageStorage"""
    
    def __init__(self, client: dropbox.Dropbox, config: DropboxConfig):
        self.client = client
        self.config = config
    
    async def list_images(self, folder: str) -> List[str]:
        """List all images in Dropbox folder"""
        try:
            path = "" if folder == "/" else folder
            result = self.client.files_list_folder(path)
            return [
                entry.name 
                for entry in result.entries 
                if isinstance(entry, dropbox.files.FileMetadata)
            ]
        except dropbox.exceptions.ApiError as e:
            raise StorageError(f"Failed to list images: {e}") from e
    
    async def download_image(self, folder: str, filename: str) -> bytes:
        """Download image from Dropbox"""
        try:
            path = os.path.join(folder, filename)
            _, response = self.client.files_download(path)
            return response.content
        except dropbox.exceptions.ApiError as e:
            raise StorageError(f"Failed to download {filename}: {e}") from e
    
    # ... other methods
```

#### 3.2.2 Class Diagram

```
┌─────────────────────────────┐
│     <<Protocol>>            │
│    ImageStorage             │
├─────────────────────────────┤
│ + list_images()             │
│ + download_image()          │
│ + get_temporary_link()      │
│ + archive_image()           │
└─────────────────────────────┘
            △
            │ implements
            │
┌─────────────────────────────┐
│    DropboxStorage           │
├─────────────────────────────┤
│ - client: Dropbox           │
│ - config: DropboxConfig     │
├─────────────────────────────┤
│ + list_images()             │
│ + download_image()          │
│ + get_temporary_link()      │
│ + archive_image()           │
└─────────────────────────────┘
```

---

### 3.3 AI Service

**Responsibility:** Coordinate image analysis and caption generation using AI models.

#### 3.3.1 Interface

```python
from typing import Protocol
from dataclasses import dataclass

@dataclass
class ImageAnalysis:
    """Result of image analysis"""
    caption: str
    mood: str
    description: str

class ImageAnalyzer(Protocol):
    """Protocol for image analysis"""
    async def analyze(self, image_url: str) -> ImageAnalysis:
        """Analyze image and return description"""
        ...

class CaptionGenerator(Protocol):
    """Protocol for caption generation"""
    async def generate(self, description: str) -> str:
        """Generate caption from description"""
        ...

class AIService:
    """Coordinates AI operations"""
    
    def __init__(
        self, 
        analyzer: ImageAnalyzer,
        generator: CaptionGenerator,
        hashtags: str = ""
    ):
        self.analyzer = analyzer
        self.generator = generator
        self.hashtags = hashtags
    
    async def create_caption(self, image_url: str) -> str:
        """
        Complete workflow: analyze image → generate caption → add hashtags
        
        Args:
            image_url: Publicly accessible URL to image
        
        Returns:
            Complete caption with hashtags
        """
        # Analyze image
        analysis = await self.analyzer.analyze(image_url)
        
        # Generate caption
        caption = await self.generator.generate(analysis.description)
        
        # Add hashtags
        if self.hashtags:
            caption = f"{caption} {self.hashtags}"
        
        return caption
```

#### 3.3.2 Implementation Classes

```python
class ReplicateAnalyzer:
    """Replicate BLIP-2 implementation"""
    
    def __init__(self, api_token: str, model: str):
        self.client = replicate.Client(api_token=api_token)
        self.model = model
    
    async def analyze(self, image_url: str) -> ImageAnalysis:
        """Analyze image using Replicate BLIP-2"""
        # Run caption generation
        caption = replicate.run(
            self.model,
            input={"image": image_url, "caption": True}
        )
        
        # Run mood analysis
        mood = replicate.run(
            self.model,
            input={
                "image": image_url, 
                "caption": False,
                "question": "What is the mood for this image?"
            }
        )
        
        description = f"{caption} {mood}"
        
        return ImageAnalysis(
            caption=caption,
            mood=mood,
            description=description
        )

class OpenAIGenerator:
    """OpenAI GPT implementation"""
    
    def __init__(self, api_key: str, engine: str, 
                 system_prompt: str, role_prompt: str):
        self.client = openai.AsyncOpenAI(api_key=api_key)
        self.engine = engine
        self.system_prompt = system_prompt
        self.role_prompt = role_prompt
    
    async def generate(self, description: str) -> str:
        """Generate caption using OpenAI"""
        try:
            response = await self.client.chat.completions.create(
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": f"{self.role_prompt} {description}"}
                ],
                model=self.engine
            )
            return response.choices[0].message.content.strip('"')
        except openai.APIError as e:
            raise AIServiceError(f"Caption generation failed: {e}") from e
```

---

### 3.4 Publishing Service

**Responsibility:** Manage content distribution to social media platforms.

#### 3.4.1 Base Interface

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

@dataclass
class PublishResult:
    """Result of publishing operation"""
    success: bool
    platform: str
    error: Optional[str] = None
    post_id: Optional[str] = None

class Publisher(ABC):
    """Abstract base class for publishers"""
    
    @property
    @abstractmethod
    def platform_name(self) -> str:
        """Name of the platform"""
        pass
    
    @abstractmethod
    def is_enabled(self) -> bool:
        """Check if publisher is enabled"""
        pass
    
    @abstractmethod
    async def publish(self, image_path: str, caption: str) -> PublishResult:
        """
        Publish image with caption to platform
        
        Args:
            image_path: Local path to image file
            caption: Caption text
        
        Returns:
            PublishResult with success status and details
        """
        pass

class PublishingService:
    """Coordinates publishing to multiple platforms"""
    
    def __init__(self, publishers: List[Publisher]):
        self.publishers = publishers
    
    async def publish_to_all(
        self, 
        image_path: str, 
        caption: str
    ) -> Dict[str, PublishResult]:
        """
        Publish to all enabled platforms in parallel
        
        Args:
            image_path: Local path to image
            caption: Caption text
        
        Returns:
            Dictionary mapping platform names to results
        """
        # Filter enabled publishers
        enabled = [p for p in self.publishers if p.is_enabled()]
        
        # Publish in parallel
        results = await asyncio.gather(
            *[p.publish(image_path, caption) for p in enabled],
            return_exceptions=True
        )
        
        # Map results to platform names
        result_map = {}
        for publisher, result in zip(enabled, results):
            if isinstance(result, Exception):
                result_map[publisher.platform_name] = PublishResult(
                    success=False,
                    platform=publisher.platform_name,
                    error=str(result)
                )
            else:
                result_map[publisher.platform_name] = result
        
        return result_map
```

#### 3.4.2 Platform Implementations

```python
class InstagramPublisher(Publisher):
    """Instagram publisher implementation"""
    
    def __init__(self, config: InstagramConfig, enabled: bool):
        self.config = config
        self.enabled = enabled
        self.client = None
    
    @property
    def platform_name(self) -> str:
        return "instagram"
    
    def is_enabled(self) -> bool:
        return self.enabled
    
    async def publish(self, image_path: str, caption: str) -> PublishResult:
        """Publish to Instagram"""
        try:
            # Initialize client with session management
            if not self.client:
                self.client = await self._create_client()
            
            # Upload photo
            media = self.client.photo_upload(image_path, caption)
            
            return PublishResult(
                success=True,
                platform=self.platform_name,
                post_id=media.id
            )
        except Exception as e:
            return PublishResult(
                success=False,
                platform=self.platform_name,
                error=str(e)
            )
    
    async def _create_client(self) -> Client:
        """Create and authenticate Instagram client"""
        client = Client()
        client.delay_range = [1, 3]
        
        # Try loading session
        try:
            client.load_settings(self.config.session_file)
            client.login(self.config.username, self.config.password)
            client.get_timeline_feed()  # Verify session
        except:
            # Fresh login
            client.login(self.config.username, self.config.password)
            client.dump_settings(self.config.session_file)
        
        return client

class TelegramPublisher(Publisher):
    """Telegram publisher implementation"""
    
    def __init__(self, config: TelegramConfig, enabled: bool):
        self.config = config
        self.enabled = enabled
    
    @property
    def platform_name(self) -> str:
        return "telegram"
    
    def is_enabled(self) -> bool:
        return self.enabled
    
    async def publish(self, image_path: str, caption: str) -> PublishResult:
        """Publish to Telegram"""
        try:
            # Resize image for Telegram
            resized_path = self._resize_for_telegram(image_path)
            
            # Send via bot
            bot = telegram.Bot(token=self.config.bot_token)
            with open(resized_path, 'rb') as f:
                message = await bot.send_photo(
                    chat_id=self.config.channel_id,
                    photo=f,
                    caption=caption
                )
            
            return PublishResult(
                success=True,
                platform=self.platform_name,
                post_id=str(message.message_id)
            )
        except Exception as e:
            return PublishResult(
                success=False,
                platform=self.platform_name,
                error=str(e)
            )
    
    def _resize_for_telegram(self, image_path: str) -> str:
        """Resize image to Telegram's optimal size"""
        from PIL import Image
        
        with Image.open(image_path) as img:
            width, height = img.size
            if width <= 1280:
                return image_path
            
            new_width = 1280
            new_height = int((new_width / width) * height)
            resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            
            resized_path = image_path.replace('.jpg', '_telegram.jpg')
            resized.save(resized_path)
            return resized_path

class EmailPublisher(Publisher):
    """Email publisher implementation"""
    
    def __init__(self, config: EmailConfig, enabled: bool):
        self.config = config
        self.enabled = enabled
    
    @property
    def platform_name(self) -> str:
        return "email"
    
    def is_enabled(self) -> bool:
        return self.enabled
    
    async def publish(self, image_path: str, caption: str) -> PublishResult:
        """Send via email"""
        try:
            msg = MIMEMultipart()
            msg['Subject'] = caption[:50]  # Truncate for subject
            msg['From'] = self.config.sender
            msg['To'] = self.config.recipient
            
            # Attach image
            with open(image_path, 'rb') as f:
                img = MIMEImage(f.read(), name=os.path.basename(image_path))
                msg.attach(img)
            
            # Attach caption
            msg.attach(MIMEText(caption))
            
            # Send via SMTP
            server = smtplib.SMTP(self.config.smtp_server, self.config.smtp_port)
            server.starttls()
            server.login(self.config.sender, self.config.password)
            server.sendmail(self.config.sender, self.config.recipient, msg.as_string())
            server.quit()
            
            return PublishResult(
                success=True,
                platform=self.platform_name
            )
        except Exception as e:
            return PublishResult(
                success=False,
                platform=self.platform_name,
                error=str(e)
            )
```

---

### 3.5 Workflow Orchestrator

**Responsibility:** Coordinate the entire posting workflow.

```python
from dataclasses import dataclass
from typing import Optional
import random

@dataclass
class WorkflowResult:
    """Result of complete workflow execution"""
    success: bool
    image_name: str
    caption: str
    publish_results: Dict[str, PublishResult]
    archived: bool
    error: Optional[str] = None

class WorkflowOrchestrator:
    """Orchestrates the complete posting workflow"""
    
    def __init__(
        self,
        config: ApplicationConfig,
        storage: ImageStorage,
        ai_service: AIService,
        publishing_service: PublishingService
    ):
        self.config = config
        self.storage = storage
        self.ai_service = ai_service
        self.publishing_service = publishing_service
    
    async def execute(self) -> WorkflowResult:
        """
        Execute complete workflow:
        1. Select random image
        2. Download image
        3. Generate caption with AI
        4. Publish to platforms
        5. Archive if successful
        
        Returns:
            WorkflowResult with execution details
        """
        try:
            # 1. Select random image
            images = await self.storage.list_images(
                self.config.dropbox.image_folder
            )
            
            if not images:
                raise WorkflowError("No images found in Dropbox folder")
            
            selected_image = random.choice(images)
            
            # 2. Download image
            image_data = await self.storage.download_image(
                self.config.dropbox.image_folder,
                selected_image
            )
            
            # Save to temporary file
            with tempfile.NamedTemporaryFile(
                suffix=os.path.splitext(selected_image)[1],
                delete=False
            ) as tmp:
                tmp.write(image_data)
                tmp_path = tmp.name
            
            try:
                # 3. Generate temporary link for AI
                temp_link = await self.storage.get_temporary_link(
                    self.config.dropbox.image_folder,
                    selected_image
                )
                
                # 4. Generate caption
                caption = await self.ai_service.create_caption(temp_link)
                
                # 5. Publish to platforms
                publish_results = await self.publishing_service.publish_to_all(
                    tmp_path,
                    caption
                )
                
                # 6. Check if any platform succeeded
                any_success = any(r.success for r in publish_results.values())
                
                # 7. Archive if successful and not in debug mode
                archived = False
                if any_success and self.config.content.archive and not self.config.content.debug:
                    await self.storage.archive_image(
                        self.config.dropbox.image_folder,
                        selected_image,
                        self.config.dropbox.archive_folder
                    )
                    archived = True
                
                return WorkflowResult(
                    success=any_success,
                    image_name=selected_image,
                    caption=caption,
                    publish_results=publish_results,
                    archived=archived
                )
            
            finally:
                # Cleanup temporary file
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
        
        except Exception as e:
            return WorkflowResult(
                success=False,
                image_name="",
                caption="",
                publish_results={},
                archived=False,
                error=str(e)
            )
```

---

## 4. Data Models

### 4.1 Domain Objects

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List
from enum import Enum

class PostStatus(Enum):
    """Status of a post"""
    PENDING = "pending"
    PROCESSING = "processing"
    PUBLISHED = "published"
    FAILED = "failed"
    ARCHIVED = "archived"

@dataclass
class Image:
    """Represents an image to be posted"""
    filename: str
    dropbox_path: str
    local_path: Optional[str] = None
    temp_link: Optional[str] = None
    size_bytes: Optional[int] = None
    format: Optional[str] = None
    
    @property
    def extension(self) -> str:
        """Get file extension"""
        return os.path.splitext(self.filename)[1]
    
    def cleanup(self):
        """Remove local file if it exists"""
        if self.local_path and os.path.exists(self.local_path):
            os.unlink(self.local_path)

@dataclass
class Caption:
    """Represents a generated caption"""
    text: str
    raw_analysis: str
    hashtags: str
    generated_at: datetime = field(default_factory=datetime.utcnow)
    
    @property
    def full_text(self) -> str:
        """Get complete caption with hashtags"""
        return f"{self.text} {self.hashtags}".strip()

@dataclass
class Post:
    """Represents a complete post"""
    id: str
    image: Image
    caption: Caption
    platforms: List[str]
    status: PostStatus
    created_at: datetime = field(default_factory=datetime.utcnow)
    published_at: Optional[datetime] = None
    archived_at: Optional[datetime] = None
    error: Optional[str] = None
    
    def mark_published(self):
        """Mark post as published"""
        self.status = PostStatus.PUBLISHED
        self.published_at = datetime.utcnow()
    
    def mark_failed(self, error: str):
        """Mark post as failed"""
        self.status = PostStatus.FAILED
        self.error = error
    
    def mark_archived(self):
        """Mark post as archived"""
        self.status = PostStatus.ARCHIVED
        self.archived_at = datetime.utcnow()
```

### 4.2 Configuration Models

Already defined in Section 3.1.2

### 4.3 API Response Models

```python
@dataclass
class DropboxFileMetadata:
    """Dropbox file metadata"""
    name: str
    path: str
    size: int
    modified: datetime

@dataclass
class ReplicateAnalysisResult:
    """Result from Replicate analysis"""
    caption: str
    mood: str
    confidence: Optional[float] = None

@dataclass
class OpenAIResponse:
    """OpenAI API response"""
    content: str
    model: str
    tokens_used: int
    finish_reason: str
```

---

## 5. API Specifications

### 5.1 Internal APIs

#### 5.1.1 Configuration API

```python
# Load configuration
config = ConfigurationManager('config.ini', '.env')
app_config = config.load()

# Validate configuration
if not config.validate():
    raise ConfigurationError("Invalid configuration")

# Access values
dropbox_folder = config.get('dropbox.image_folder')
enabled_platforms = config.get_section('platforms')
```

#### 5.1.2 Storage API

```python
# List images
images = await storage.list_images('/Images/ToPost')
# Returns: ['photo1.jpg', 'photo2.jpg', ...]

# Download image
image_data = await storage.download_image('/Images/ToPost', 'photo1.jpg')
# Returns: bytes

# Get temporary link
link = await storage.get_temporary_link('/Images/ToPost', 'photo1.jpg')
# Returns: 'https://dl.dropboxusercontent.com/...'

# Archive image
await storage.archive_image('/Images/ToPost', 'photo1.jpg', 'archive')
# Moves: /Images/ToPost/photo1.jpg → /Images/ToPost/archive/photo1.jpg
```

#### 5.1.3 AI API

```python
# Analyze image
analysis = await analyzer.analyze('https://example.com/image.jpg')
# Returns: ImageAnalysis(caption="...", mood="...", description="...")

# Generate caption
caption = await generator.generate("A beautiful sunset over mountains")
# Returns: "Golden hour magic at its finest..."

# Complete workflow
ai_service = AIService(analyzer, generator, hashtags="#photo #art")
full_caption = await ai_service.create_caption(image_url)
# Returns: "Golden hour magic at its finest... #photo #art"
```

#### 5.1.4 Publishing API

```python
# Publish to single platform
result = await instagram_publisher.publish('/tmp/photo.jpg', 'Caption here')
# Returns: PublishResult(success=True, platform='instagram', post_id='123')

# Publish to all platforms
results = await publishing_service.publish_to_all('/tmp/photo.jpg', 'Caption')
# Returns: {
#     'instagram': PublishResult(success=True, ...),
#     'telegram': PublishResult(success=True, ...),
#     'email': PublishResult(success=False, error='...')
# }
```

---

### 5.2 External API Integration

#### 5.2.1 Dropbox API

**Endpoints Used:**
- `files/list_folder` - List folder contents
- `files/download` - Download file
- `files/get_temporary_link` - Get shareable link
- `files/move_v2` - Move file (for archiving)

**Authentication:** OAuth2 with refresh token

**Rate Limits:** 
- 200 requests per second per app
- 600 requests per hour per user

**Error Handling:**
```python
try:
    result = dbx.files_list_folder(path)
except dropbox.exceptions.ApiError as e:
    if e.error.is_path():
        # Handle path errors (not found, invalid, etc.)
        pass
    elif e.error.is_other():
        # Handle other errors
        pass
```

---

#### 5.2.2 OpenAI API

**Endpoint:** `POST /v1/chat/completions`

**Request Format:**
```json
{
  "model": "gpt-3.5-turbo",
  "messages": [
    {"role": "system", "content": "You are a social media expert..."},
    {"role": "user", "content": "Write a caption for: A sunset over mountains"}
  ]
}
```

**Response Format:**
```json
{
  "id": "chatcmpl-123",
  "choices": [
    {
      "message": {
        "role": "assistant",
        "content": "Golden hour magic..."
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 50,
    "completion_tokens": 20,
    "total_tokens": 70
  }
}
```

**Rate Limits:**
- GPT-3.5-Turbo: 3,500 requests/minute
- GPT-4: 200 requests/minute

---

#### 5.2.3 Replicate API

**Endpoint:** `POST /v1/predictions`

**Request Format:**
```json
{
  "version": "model_version_hash",
  "input": {
    "image": "https://example.com/image.jpg",
    "caption": true,
    "question": "What is the mood?",
    "temperature": 1
  }
}
```

**Response Format:**
```json
{
  "id": "prediction_id",
  "status": "succeeded",
  "output": "A serene landscape with mountains at sunset"
}
```

**Rate Limits:**
- 50 requests per minute
- Varies by model pricing

---

#### 5.2.4 Telegram Bot API

**Endpoint:** `POST https://api.telegram.org/bot{token}/sendPhoto`

**Request Format:**
```
Content-Type: multipart/form-data

chat_id: @channel_name
photo: <binary_data>
caption: Caption text here
```

**Response Format:**
```json
{
  "ok": true,
  "result": {
    "message_id": 123,
    "date": 1234567890,
    "chat": {...},
    "photo": [...]
  }
}
```

**Rate Limits:**
- 30 messages per second
- 20 messages per minute to same chat

---

#### 5.2.5 Instagram API (instagrapi)

**Note:** Unofficial API - use at own risk

**Methods Used:**
- `client.login(username, password)` - Authenticate
- `client.photo_upload(path, caption)` - Upload photo
- `client.load_settings(file)` - Load session
- `client.dump_settings(file)` - Save session

**Rate Limits (Approximat):**
- 200-500 actions per hour
- Instagram actively detects automated behavior

---

## 6. Database Design (Future Option)

### 6.1 Current State

**No database currently used.** Application is stateless.

### 6.2 Recommended Database Schema

For future enhancements, implement SQLite database:

```sql
-- Posts table
CREATE TABLE posts (
    id TEXT PRIMARY KEY,
    image_filename TEXT NOT NULL,
    image_dropbox_path TEXT NOT NULL,
    caption_text TEXT NOT NULL,
    caption_hashtags TEXT,
    status TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    published_at TIMESTAMP,
    archived_at TIMESTAMP,
    error TEXT
);

-- Post platforms (many-to-many)
CREATE TABLE post_platforms (
    post_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    success BOOLEAN NOT NULL,
    post_id_on_platform TEXT,
    error TEXT,
    published_at TIMESTAMP,
    PRIMARY KEY (post_id, platform),
    FOREIGN KEY (post_id) REFERENCES posts(id)
);

-- Image analysis cache
CREATE TABLE image_analysis_cache (
    image_path TEXT PRIMARY KEY,
    caption TEXT NOT NULL,
    mood TEXT NOT NULL,
    description TEXT NOT NULL,
    analyzed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Configuration history
CREATE TABLE config_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    config_key TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT NOT NULL,
    changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    changed_by TEXT
);

-- Posting schedule
CREATE TABLE posting_schedule (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    image_filename TEXT NOT NULL,
    scheduled_time TIMESTAMP NOT NULL,
    status TEXT DEFAULT 'pending',
    executed_at TIMESTAMP
);

-- Analytics
CREATE TABLE post_analytics (
    post_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    metric_value REAL NOT NULL,
    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (post_id) REFERENCES posts(id)
);

-- Indexes for performance
CREATE INDEX idx_posts_status ON posts(status);
CREATE INDEX idx_posts_created ON posts(created_at);
CREATE INDEX idx_post_platforms_platform ON post_platforms(platform);
CREATE INDEX idx_schedule_time ON posting_schedule(scheduled_time);
```

---

## 7. Security Architecture

### 7.1 Authentication & Authorization

#### 7.1.1 Credential Management

**Current Approach:**
```
.env file → Plain text storage → High risk
```

**Recommended Approach:**
```
System Keyring → Encrypted storage → Secure access
```

**Implementation:**
```python
import keyring
from cryptography.fernet import Fernet

class SecureCredentialManager:
    """Manage credentials securely"""
    
    def __init__(self, service_name: str = "socialmedia_publisher"):
        self.service = service_name
        self._cipher = self._init_cipher()
    
    def _init_cipher(self) -> Fernet:
        """Initialize encryption cipher"""
        key = keyring.get_password(self.service, "encryption_key")
        if not key:
            key = Fernet.generate_key().decode()
            keyring.set_password(self.service, "encryption_key", key)
        return Fernet(key.encode())
    
    def store_credential(self, key: str, value: str):
        """Store credential securely"""
        encrypted = self._cipher.encrypt(value.encode())
        keyring.set_password(self.service, key, encrypted.decode())
    
    def get_credential(self, key: str) -> Optional[str]:
        """Retrieve credential securely"""
        encrypted = keyring.get_password(self.service, key)
        if not encrypted:
            return None
        decrypted = self._cipher.decrypt(encrypted.encode())
        return decrypted.decode()
```

#### 7.1.2 Session Management

```python
class SessionManager:
    """Manage platform sessions securely"""
    
    def __init__(self, storage_path: Path, encryption_key: bytes):
        self.storage_path = storage_path
        self.cipher = Fernet(encryption_key)
    
    def save_session(self, platform: str, session_data: dict):
        """Save encrypted session"""
        json_data = json.dumps(session_data)
        encrypted = self.cipher.encrypt(json_data.encode())
        
        session_file = self.storage_path / f"{platform}_session.enc"
        with open(session_file, 'wb') as f:
            f.write(encrypted)
    
    def load_session(self, platform: str) -> Optional[dict]:
        """Load and decrypt session"""
        session_file = self.storage_path / f"{platform}_session.enc"
        if not session_file.exists():
            return None
        
        with open(session_file, 'rb') as f:
            encrypted = f.read()
        
        decrypted = self.cipher.decrypt(encrypted)
        return json.loads(decrypted)
```

---

### 7.2 Data Protection

#### 7.2.1 File System Security

```python
class SecureFileHandler:
    """Handle files with security best practices"""
    
    @staticmethod
    def create_secure_temp_file(suffix: str = '') -> tuple[int, str]:
        """Create temp file with restrictive permissions"""
        fd, path = tempfile.mkstemp(suffix=suffix)
        os.chmod(path, 0o600)  # Owner read/write only
        return fd, path
    
    @staticmethod
    def secure_delete(filepath: str):
        """Overwrite and delete file"""
        if not os.path.exists(filepath):
            return
        
        # Overwrite with random data
        size = os.path.getsize(filepath)
        with open(filepath, 'wb') as f:
            f.write(secrets.token_bytes(size))
        
        # Delete
        os.unlink(filepath)
    
    @contextlib.contextmanager
    def secure_temporary_file(self, suffix: str = ''):
        """Context manager for secure temporary files"""
        fd, path = self.create_secure_temp_file(suffix)
        try:
            yield path
        finally:
            os.close(fd)
            self.secure_delete(path)
```

#### 7.2.2 Logging Security

```python
class SecureLogger:
    """Logger that sanitizes sensitive information"""
    
    SENSITIVE_PATTERNS = [
        (r'sk-[A-Za-z0-9]{48}', '[OPENAI_KEY_REDACTED]'),
        (r'r8_[A-Za-z0-9]+', '[REPLICATE_TOKEN_REDACTED]'),
        (r'[0-9]{10}:[A-Za-z0-9_-]{35}', '[TELEGRAM_TOKEN_REDACTED]'),
        (r'"password"\s*:\s*"[^"]*"', '"password": "[REDACTED]"'),
    ]
    
    @classmethod
    def sanitize(cls, message: str) -> str:
        """Remove sensitive information from message"""
        sanitized = message
        for pattern, replacement in cls.SENSITIVE_PATTERNS:
            sanitized = re.sub(pattern, replacement, sanitized)
        return sanitized
    
    @classmethod
    def safe_log_error(cls, logger: logging.Logger, error: Exception):
        """Log error with sanitization"""
        sanitized_msg = cls.sanitize(str(error))
        logger.error(sanitized_msg)
```

---

### 7.3 Network Security

```python
class SecureHTTPClient:
    """HTTP client with security best practices"""
    
    def __init__(self, timeout: int = 30, verify_ssl: bool = True):
        self.session = self._create_session(timeout, verify_ssl)
    
    def _create_session(self, timeout: int, verify_ssl: bool) -> requests.Session:
        """Create secure requests session"""
        session = requests.Session()
        
        # SSL verification
        session.verify = verify_ssl
        
        # Timeout
        session.timeout = timeout
        
        # Retry strategy
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"]
        )
        
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        
        # Security headers
        session.headers.update({
            'User-Agent': 'SocialMediaPublisher/1.0',
            'Accept': 'application/json',
        })
        
        return session
```

---

## 8. Deployment Architecture

### 8.1 Local Development

```
Developer Machine
├── Python 3.9+ Environment
├── Virtual Environment (venv)
├── Development Dependencies
├── .env (local credentials)
├── config.ini (local settings)
└── Manual Execution
```

### 8.2 Scheduled Execution (Cron)

```
Linux/macOS Server
├── Python 3.9+ Environment
├── Virtual Environment (venv)
├── Production Dependencies Only
├── Secure Credential Storage (Keyring)
├── Encrypted Configuration
├── Cron Job Scheduler
│   └── Daily at 9 AM: Execute Script
├── Log Files (Rotated)
└── Monitoring (Optional)
```

**Cron Configuration:**
```bash
# Edit crontab
crontab -e

# Add job
0 9 * * * cd /opt/socialmedia && /opt/socialmedia/venv/bin/python py_rotator_daily.py /opt/socialmedia/config/production.ini >> /var/log/socialmedia/app.log 2>&1
```

### 8.3 Containerized Deployment (Docker)

```dockerfile
# Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Create non-root user
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app
USER appuser

# Run application
CMD ["python", "py_rotator_daily.py", "config/config.ini"]
```

**docker-compose.yml:**
```yaml
version: '3.8'

services:
  socialmedia-publisher:
    build: .
    container_name: socialmedia_publisher
    volumes:
      - ./config:/app/config:ro
      - ./logs:/app/logs
      - sessions:/app/sessions
    environment:
      - PYTHONUNBUFFERED=1
    restart: unless-stopped
    # Schedule with cron in container or external scheduler

volumes:
  sessions:
```

### 8.4 Cloud Deployment (AWS Lambda)

```
AWS Lambda Function
├── Python 3.9+ Runtime
├── Dependencies (Layer)
├── Application Code
├── Environment Variables (encrypted)
├── CloudWatch Events Trigger (Schedule)
└── CloudWatch Logs
```

**Lambda Handler:**
```python
import asyncio
from workflow_orchestrator import WorkflowOrchestrator

def lambda_handler(event, context):
    """AWS Lambda handler"""
    try:
        # Initialize orchestrator
        orchestrator = WorkflowOrchestrator.from_env()
        
        # Run workflow
        result = asyncio.run(orchestrator.execute())
        
        return {
            'statusCode': 200 if result.success else 500,
            'body': json.dumps({
                'success': result.success,
                'image': result.image_name,
                'platforms': list(result.publish_results.keys())
            })
        }
    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }
```

---

## 9. Integration Patterns

### 9.1 Retry Pattern

```python
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type
)

class APIClient:
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((ConnectionError, TimeoutError)),
        reraise=True
    )
    async def call_api(self, *args, **kwargs):
        """API call with automatic retries"""
        # Implementation
        pass
```

### 9.2 Circuit Breaker Pattern

```python
from datetime import datetime, timedelta

class CircuitBreaker:
    """Circuit breaker to prevent cascading failures"""
    
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        expected_exception: type = Exception
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        self.failure_count = 0
        self.last_failure_time = None
        self.state = "closed"  # closed, open, half_open
    
    def call(self, func, *args, **kwargs):
        """Execute function with circuit breaker"""
        if self.state == "open":
            if self._should_attempt_reset():
                self.state = "half_open"
            else:
                raise CircuitBreakerOpen("Circuit breaker is OPEN")
        
        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except self.expected_exception as e:
            self._on_failure()
            raise
    
    def _on_success(self):
        """Handle successful call"""
        self.failure_count = 0
        self.state = "closed"
    
    def _on_failure(self):
        """Handle failed call"""
        self.failure_count += 1
        self.last_failure_time = datetime.now()
        
        if self.failure_count >= self.failure_threshold:
            self.state = "open"
    
    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt reset"""
        return (
            datetime.now() - self.last_failure_time
            > timedelta(seconds=self.recovery_timeout)
        )
```

### 9.3 Bulkhead Pattern

```python
import asyncio
from asyncio import Semaphore

class ServiceBulkhead:
    """Isolate services to prevent cascading failures"""
    
    def __init__(self, max_concurrent: int = 5):
        self.semaphore = Semaphore(max_concurrent)
    
    async def execute(self, coro):
        """Execute coroutine with concurrency limit"""
        async with self.semaphore:
            return await coro

# Usage
instagram_bulkhead = ServiceBulkhead(max_concurrent=2)
telegram_bulkhead = ServiceBulkhead(max_concurrent=5)

# Ensure Instagram doesn't overwhelm with concurrent requests
await instagram_bulkhead.execute(
    publisher.publish(image, caption)
)
```

---

## 10. Future Enhancements

### 10.1 Short-Term (3-6 months)

#### 10.1.1 Video Support

```python
class VideoProcessor:
    """Process videos for social media"""
    
    async def transcode(
        self,
        input_path: str,
        platform: str
    ) -> str:
        """Transcode video for platform requirements"""
        # Use ffmpeg for transcoding
        pass
    
    async def generate_thumbnail(
        self,
        video_path: str
    ) -> str:
        """Generate thumbnail from video"""
        pass

class VideoPublisher(Publisher):
    """Publish videos to platforms"""
    
    async def publish(
        self,
        video_path: str,
        caption: str,
        thumbnail: Optional[str] = None
    ) -> PublishResult:
        """Publish video content"""
        pass
```

#### 10.1.2 Content Scheduling

```python
from datetime import datetime

class ContentScheduler:
    """Schedule content for future posting"""
    
    def schedule_post(
        self,
        image: Image,
        platforms: List[str],
        scheduled_time: datetime
    ):
        """Schedule a post for future execution"""
        pass
    
    async def process_due_posts(self):
        """Process all posts that are due"""
        pass
```

### 10.2 Medium-Term (6-12 months)

#### 10.2.1 Analytics Dashboard

```python
class AnalyticsCollector:
    """Collect posting analytics"""
    
    async def collect_instagram_stats(self, post_id: str) -> dict:
        """Collect Instagram post statistics"""
        # Likes, comments, reach, impressions
        pass
    
    async def collect_telegram_stats(self, post_id: str) -> dict:
        """Collect Telegram post statistics"""
        # Views, forwards
        pass
    
    def generate_report(self, start_date: datetime, end_date: datetime):
        """Generate analytics report"""
        pass
```

#### 10.2.2 A/B Testing

```python
class CaptionTester:
    """A/B test different caption styles"""
    
    def create_variants(self, base_caption: str) -> List[str]:
        """Create caption variants"""
        pass
    
    async def test_captions(
        self,
        image: Image,
        variants: List[str]
    ) -> str:
        """Test which caption performs better"""
        pass
```

### 10.3 Long-Term (12+ months)

#### 10.3.1 Multi-Tenant Support

```python
class TenantManager:
    """Manage multiple users/organizations"""
    
    def create_tenant(self, tenant_id: str, config: dict):
        """Create new tenant"""
        pass
    
    async def execute_for_tenant(self, tenant_id: str):
        """Execute workflow for specific tenant"""
        pass
```

#### 10.3.2 Machine Learning Optimization

```python
class MLOptimizer:
    """Use ML to optimize posting"""
    
    async def predict_best_time(
        self,
        content_type: str,
        historical_data: List[dict]
    ) -> datetime:
        """Predict best time to post"""
        pass
    
    async def optimize_hashtags(
        self,
        image: Image,
        caption: str
    ) -> List[str]:
        """Suggest optimal hashtags"""
        pass
```

---

## Appendix

### A. Design Principles

1. **Separation of Concerns**: Each component has a single, well-defined responsibility
2. **Dependency Injection**: Components receive dependencies rather than creating them
3. **Interface Segregation**: Clients depend on minimal interfaces
4. **Open/Closed Principle**: Open for extension, closed for modification
5. **DRY (Don't Repeat Yourself)**: Reuse code through abstraction
6. **KISS (Keep It Simple, Stupid)**: Prefer simple solutions
7. **YAGNI (You Aren't Gonna Need It)**: Don't build what you don't need yet

### B. Technology Stack Evolution

**Current Stack:**
```
Python 3.7+ → asyncio → dropbox → openai → replicate → instagrapi → telegram
```

**Recommended Stack:**
```
Python 3.11+ → asyncio → aiohttp → pydantic → SQLAlchemy → FastAPI (future)
```

### C. API Design Guidelines

1. **Consistent naming**: Use clear, descriptive names
2. **Type hints**: Always use type annotations
3. **Docstrings**: Document all public APIs
4. **Error handling**: Use specific exception types
5. **Async by default**: For I/O operations
6. **Immutability**: Prefer immutable data structures
7. **Protocols over inheritance**: Use Protocol for interfaces

### D. Performance Targets

| Metric | Target | Current |
|--------|--------|---------|
| End-to-end execution time | < 30s | ~40s |
| Time to first platform post | < 20s | ~30s |
| Memory usage | < 200MB | ~150MB |
| Concurrent platform posts | 3+ | Sequential |
| Recovery time from failure | < 5s | N/A |

---

**Document Version:** 1.0  
**Last Updated:** October 31, 2025  
**Status:** Living Document - Updated as system evolves

*For questions or clarifications, please refer to the project repository or maintainer.*
