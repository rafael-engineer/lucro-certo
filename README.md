# Lucro Certo - Gestão Inteligente de Custos para Microempreendedores Alimentícios

**Acesse a aplicação em: [https://lucrocerto.rafael.engineer](https://lucrocerto.rafael.engineer)**

---

Lucro Certo é uma aplicação web nativa em nuvem (Cloud Native) desenvolvida para transformar a gestão financeira de microempreendedores do setor alimentício. A ferramenta simplifica radicalmente o controle de estoque, a precificação e o gerenciamento de desperdícios, substituindo planilhas complexas por automação inteligente.

A principal inovação do projeto é o uso de Inteligência Artificial Generativa Multimodal para automatizar a entrada de dados através da leitura de notas fiscais, eliminando a barreira da digitação manual e garantindo precisão nos cálculos de custo.

Este projeto foi desenvolvido como parte da disciplina Projeto Aplicado do curso de Análise e Desenvolvimento de Software da Faculdade QI, sob orientação do Prof. Rodrigo Barreto (rodrigo.barreto@qi.edu.br).

## 🎯 O Problema

Microempreendedores (como confeiteiros, donos de marmitarias e pequenos restaurantes) enfrentam desafios críticos:

*   **Flutuação de Preços:** O custo dos insumos (leite, farinha, gás) muda diariamente, tornando a precificação estática obsoleta.
*   **Gestão Manual:** O controle via caderno ou planilhas é propenso a erros e consome tempo valioso de produção.
*   **Incerteza do Lucro:** Sem saber o custo exato da receita no dia, é impossível calcular a margem de lucro real.
*   **Desperdícios Invisíveis:** Perdas por validade ou erro de preparo raramente são contabilizadas no custo final.

## 💡 A Solução: Lucro Certo

O Lucro Certo atua como um "Ledger Inteligente" (livro-razão) que:

*   Automatiza a entrada de estoque via foto da nota fiscal.
*   Calcula o custo real das receitas baseado no preço médio do estoque atual.
*   Sugere preços de venda com base na margem de lucro desejada.
*   Monitora desperdícios e alerta sobre estoques críticos.

## 🚀 Funcionalidades Principais

### 1. 📸 Entrada de Estoque via IA com Fuzzy Matching (Destaque)

A funcionalidade mais avançada do sistema. O usuário tira uma foto da nota fiscal e a IA (GPT-4o) extrai os dados.

*   **OCR Inteligente:** Lê nomes, quantidades e preços, mesmo em notas amassadas ou com layouts variados.
*   **Normalização Automática de Unidades:** Converte automaticamente unidades de compra (ex: 1kg, 2L) para unidades base de estoque (G, ML), garantindo consistência matemática.
*   **Fuzzy Matching Contextual (Inovação):**
    *   O sistema envia para a IA a lista atual de itens do estoque do usuário.
    *   A IA utiliza essa lista para padronizar nomes. Se o estoque tem "LEITE INTEGRAL" e a nota diz "LEITE UHT SANTA CLARA", a IA entende que é o mesmo produto e sugere a unificação automaticamente.
    *   Isso evita a duplicidade de itens ("Leite" vs "Leite Integral") e mantém o histórico de preço médio limpo.

### 2. 📦 Gestão de Estoque Híbrida

*   **Entrada Manual:** Para compras sem nota ou ajustes rápidos, com autocomplete inteligente baseado no histórico.
*   **Normalização Retroativa:** Ferramenta dedicada para fundir itens duplicados (ex: unificar "Ovos Brancos" e "Ovos Vermelhos" em "Ovos"), atualizando todo o histórico de transações passadas.
*   **Limpeza de Dados:** Funcionalidades para remover itens específicos ou resetar o estoque para testes.

### 3. 🍰 Calculadora de Receitas e Precificação Dinâmica (Bidirecional)

*   **Custo Real:** Monta receitas selecionando ingredientes do estoque. O custo é calculado usando o Preço Médio Ponderado real de compra, não um valor estimado.
*   **Custos Extras:** Permite adicionar custos não-estocáveis (Gás, Embalagem, Mão de Obra).
*   **Precificação Interconectada:**
    *   Ao alterar a Margem de Lucro (%), o sistema recalcula o Preço de Venda.
    *   Ao alterar o Preço de Venda, o sistema recalcula a Margem de Lucro (%).
*   **Catálogo de Produtos:** Salva receitas como "Produtos" prontos para venda rápida.

### 4. 💸 Registro e Gestão de Vendas

*   **Registro de Venda:** Permite registrar a venda de um produto do catálogo, informando quantidade, preço final e dados do cliente.
*   **Baixa Automática de Estoque:** Ao registrar a venda, o sistema automaticamente deduz a quantidade proporcional de todos os ingredientes da receita do estoque.
*   **Gerenciamento de Histórico:** Uma nova aba "Gerenciar Vendas" permite visualizar todas as vendas passadas, com a opção de excluir registros incorretos. A exclusão de uma venda também reverte a baixa de estoque dos ingredientes, mantendo a consistência dos dados.

### 5. 🗑️ Gestão de Desperdícios

*   Módulo específico para registrar perdas de insumos ou produtos prontos.
*   Categorização de motivos (ex: "Vencimento", "Queda", "Erro de Preparo") para análise gerencial.
*   Calcula o Prejuízo Financeiro (custo do insumo) e o Prejuízo de Oportunidade (valor de venda perdido).

### 6. 📊 Dashboard Gerencial (Visão Geral)

*   **Fluxo de Caixa Real:** Diferencia entradas operacionais (Vendas) de custos de reposição (Compras).
*   **Alertas de Estoque Inteligentes:** Monitora apenas o estoque de *ingredientes*, ignorando registros de vendas e desperdícios, para fornecer alertas precisos sobre o que precisa ser comprado.
*   **Análise de Performance:** Rankings de produtos mais vendidos e análise de causas de desperdício.

## 🛠️ Arquitetura e Tecnologias

A escolha da stack tecnológica priorizou escalabilidade, velocidade de desenvolvimento (Time-to-Market) e robustez corporativa.

### Backend & Frontend: Streamlit (Python)
**Motivação:** A escolha do Streamlit permitiu a unificação do desenvolvimento Frontend e Backend em uma única base de código Python. Isso eliminou a complexidade de gerenciar APIs REST separadas e sincronização de estado entre cliente/servidor, permitindo focar 100% na regra de negócio complexa (calculos financeiros e integração com IA). Para um MVP validado rapidamente, é a escolha mais eficiente.

### Banco de Dados: Azure Cosmos DB (API for NoSQL)
**Motivação da Escolha:** A natureza dos dados de notas fiscais é inerentemente não estruturada e polimórfica. Itens de compra variam drasticamente em atributos. O Azure Cosmos DB foi escolhido por sua capacidade de schema-less (NoSQL), permitindo salvar transações complexas (com listas aninhadas de ingredientes) sem migrações de banco de dados rígidas.
**Escalabilidade Global:** A latência de milissegundos (single-digit) garante que a aplicação responda instantaneamente mesmo em dispositivos móveis, essencial para o uso em cozinhas dinâmicas.
**Serverless:** O modelo de capacidade Serverless ajusta o custo automaticamente ao uso real, ideal para o perfil de uso esporádico (picos de lançamento) de microempreendedores.

### Inteligência Artificial: Azure OpenAI Service (GPT-4o)
**Motivação:** O modelo GPT-4o multimodal oferece a melhor capacidade de OCR contextual do mercado. Diferente de OCRs tradicionais que apenas leem texto, o LLM entende o contexto ("isto é um desconto", "isto é uma unidade de medida implícita"), permitindo a normalização de dados complexos (L para ML, KG para G) que seria impossível com regex tradicional.

### Infraestrutura: Azure Container Apps
**Motivação:** Orquestração de containers sem a complexidade de gestão de clusters Kubernetes (K8s). Permite deploy contínuo a partir do Docker Registry, escalabilidade automática (scale-to-zero) para economia de custos e gerenciamento simplificado de certificados SSL/TLS.

## ⚙️ Instalação e Execução Local

### Pré-requisitos
*   Python 3.10+
*   Conta no Microsoft Azure (para Cosmos DB)
*   Chave de API da OpenAI

### Passos

1.  **Clone o repositório:**
    ```bash
    git clone https://github.com/rafael-engineer/lucro-certo.git
    cd lucro-certo
    ```

2.  **Crie o ambiente virtual:**
    ```bash
    python -m venv venv
    
    # Windows
    .\venv\Scripts\activate
    
    # Linux/Mac
    source venv/bin/activate
    ```

3.  **Instale as dependências:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configure as variáveis de ambiente:**
    Crie um arquivo `.env` na raiz do projeto:
    ```env
    COSMOS_ENDPOINT="sua_url_do_cosmos_db"
    COSMOS_KEY="sua_chave_primaria_do_cosmos"
    OPENAI_API_KEY="sua_chave_da_openai"
    ```

5.  **Execute a aplicação:**
    ```bash
    streamlit run app.py
    ```

---

## 👨‍💻 Desenvolvedor

**Rafael da Silva Santos**
*   DevOps Senior & Full Stack Developer
*   Email: `contact@rafael.engineer`
*   Portfolio: [https://www.rafael.engineer](https://www.rafael.engineer)

*Desenvolvido com paixão para empoderar pequenos negócios.* 🚀
